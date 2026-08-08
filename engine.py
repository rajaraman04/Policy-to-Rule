from __future__ import annotations
import csv
import difflib
import json
import os
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).parent / "data"
POLICY_DIR = DATA_DIR / "policies"
CLAIMS_PATH = DATA_DIR / "sample_claims.csv"
CACHE_PATH = DATA_DIR / "cached_rules.json"
DEFAULT_MODEL = os.environ.get("POLICY_MODEL", "claude-sonnet-4-6")
ALLOWED_FIELDS = ["cpt_code", "modifiers", "units", "member_age", "member_sex","place_of_service", "provider_specialty", "billed_amount", "dos",]
ALLOWED_OPS = ["equals", "not_equals", "in", "not_in", "greater_than", "less_than","gte", "lte", "in_range", "not_in_range", "contains", "not_contains","exists", "not_exists",]

def load_claims(path: str | Path = CLAIMS_PATH) -> list[dict[str, Any]]:
    """Read the claims CSV into a list of dict rows (values stay as strings)."""
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def load_sample_policy(stem: str) -> str:
    return (POLICY_DIR / f"{stem}.txt").read_text(encoding="utf-8")

def list_sample_policies() -> list[str]:
    return sorted(p.stem for p in POLICY_DIR.glob("*.txt"))

def _load_cache() -> dict[str, Any]:
    return json.loads(CACHE_PATH.read_text(encoding="utf-8"))

#helpers
def _as_number(value: Any) -> float:
    return float(str(value).strip())


def _tokens(value: Any) -> set[str]:
    """Split a multi-value cell (e.g. modifiers '25|50') into a set of tokens."""
    raw = str(value)
    for sep in ("|", ",", ";", " "):
        raw = raw.replace(sep, "\n")
    return {t.strip() for t in raw.split("\n") if t.strip()}


# ---------- 1. deterministic rule application ----------
def evaluate_condition(claim: dict[str, Any], cond: dict[str, Any]) -> bool:
    """Evaluate one {field, op, value} condition against a single claim row."""
    field, op = cond["field"], cond["op"]
    value = cond.get("value")
    actual = claim.get(field, "")

    if op == "exists":
        return str(actual).strip() != ""
    if op == "not_exists":
        return str(actual).strip() == ""
    if op == "equals":
        return str(actual).strip() == str(value).strip()
    if op == "not_equals":
        return str(actual).strip() != str(value).strip()
    if op == "in":
        return str(actual).strip() in [str(v).strip() for v in value]
    if op == "not_in":
        return str(actual).strip() not in [str(v).strip() for v in value]
    if op == "contains":
        return str(value).strip() in _tokens(actual)
    if op == "not_contains":
        return str(value).strip() not in _tokens(actual)

    if op in ("greater_than", "less_than", "gte", "lte", "in_range", "not_in_range"):
        try:
            n = _as_number(actual)
        except ValueError:
            return False
        if op == "greater_than":
            return n > _as_number(value)
        if op == "less_than":
            return n < _as_number(value)
        if op == "gte":
            return n >= _as_number(value)
        if op == "lte":
            return n <= _as_number(value)
        low, high = _as_number(value[0]), _as_number(value[1])
        if op == "in_range":
            return low <= n <= high
        return not (low <= n <= high)  # not_in_range

    raise ValueError(f"Unsupported operator: {op}")


def apply_rule(rule: dict[str, Any], claims: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Run one rule over all claims. Returns one result per claim:
    {claim, matched, action, message}. 'combine'="all" is AND; "any" is OR.
    """
    combine = rule.get("combine", "all")
    conditions = rule.get("conditions", [])
    results = []
    for claim in claims:
        checks = [evaluate_condition(claim, c) for c in conditions]
        matched = all(checks) if combine == "all" else any(checks)
        results.append({
            "claim": claim,
            "matched": matched,
            "action": rule.get("action", "FLAG") if matched else "PASS",
            "message": rule.get("message", "") if matched else "",
        })
    return results


def validate_rule(rule: dict[str, Any]) -> list[str]:
    """Return a list of problems with a rule (empty list == valid)."""
    problems = []
    for key in ("action", "conditions"):
        if key not in rule:
            problems.append(f"missing required key: {key}")
    for i, cond in enumerate(rule.get("conditions", [])):
        if cond.get("field") not in ALLOWED_FIELDS:
            problems.append(f"condition {i}: unknown field {cond.get('field')!r}")
        if cond.get("op") not in ALLOWED_OPS:
            problems.append(f"condition {i}: unknown operator {cond.get('op')!r}")
    return problems

#policy difference
def diff_policies(text_a: str, text_b: str,
                  label_a: str = "v1", label_b: str = "v2") -> str:
    a, b = text_a.splitlines(), text_b.splitlines()
    return "\n".join(difflib.unified_diff(a, b, fromfile=label_a, tofile=label_b, lineterm=""))

# 3 & 4. LLM-assisted steps (fall back to cache when no API key is present)
# --------------------------------------------------------------------------- #
_SYSTEM_PROMPT = f"""You convert written U.S. healthcare billing/coding policies into a \
structured, machine-executable rule. Output ONLY a single JSON object, no prose, no code fences.

The rule schema is:
{{
  "rule_id": "<short id from the policy, e.g. PP-1042>",
  "name": "<short human name>",
  "description": "<one sentence on what it flags>",
  "source_policy": "<policy id and effective date>",
  "action": "FLAG" | "DENY" | "INFO",
  "message": "<message to show when a claim matches>",
  "combine": "all" | "any",
  "conditions": [ {{"field": <field>, "op": <op>, "value": <value>}} ]
}}

You MUST only use these fields: {ALLOWED_FIELDS}
You MUST only use these operators: {ALLOWED_OPS}
For in_range / not_in_range, value is a two-item [low, high] list (inclusive).
For contains / not_contains, value is a single token (e.g. a modifier like "50").
Keep codes as strings. Return the JSON object only."""


def _extract_json(text: str) -> dict[str, Any]:
    """Pull the first JSON object out of a model response, tolerating stray fences/text."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1]
        if text.lstrip().startswith("json"):
            text = text.lstrip()[4:]
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("no JSON object found in model response")
    return json.loads(text[start:end + 1])


def _have_key() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def policy_to_rule(policy_text: str, sample_stem: str | None = None,
                   model: str | None = None) -> tuple[dict[str, Any], str]:
    """
    Convert a policy into a structured rule.
    Returns (rule_dict, source) where source is "live-llm" or "cache".
    """
    if _have_key():
        import anthropic  # imported lazily so the deterministic core needs no SDK
        client = anthropic.Anthropic()
        resp = client.messages.create(
            model=model or DEFAULT_MODEL,
            max_tokens=1200,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": f"Policy:\n\n{policy_text}"}],
        )
        rule = _extract_json(resp.content[0].text)
        problems = validate_rule(rule)
        if problems:
            raise ValueError("model produced an invalid rule: " + "; ".join(problems))
        return rule, "live-llm"

    # ---- offline fallback ----
    cache = _load_cache()
    if sample_stem and sample_stem in cache["rules"]:
        return cache["rules"][sample_stem], "cache"
    raise RuntimeError(
        "No ANTHROPIC_API_KEY set and no cached rule for this policy. "
        "Set an API key for live conversion, or load one of the sample policies."
    )


def summarize_change(text_a: str, text_b: str, cache_key: str | None = None,
                     model: str | None = None) -> tuple[str, str]:
    """Plain-English summary of what changed between two policy versions."""
    if _have_key():
        import anthropic
        client = anthropic.Anthropic()
        prompt = (
            "Two versions of a healthcare payment policy are below. In 3-4 sentences, "
            "summarize what changed and the operational impact on claim flagging. Be concrete.\n\n"
            f"--- VERSION A ---\n{text_a}\n\n--- VERSION B ---\n{text_b}"
        )
        resp = client.messages.create(
            model=model or DEFAULT_MODEL,
            max_tokens=400,
            messages=[{"role": "user", "content": prompt}],
        )
        return resp.content[0].text.strip(), "live-llm"

    cache = _load_cache()
    if cache_key and cache_key in cache.get("change_summaries", {}):
        return cache["change_summaries"][cache_key], "cache"
    raise RuntimeError("No API key set and no cached summary for this comparison.")