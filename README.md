# Policy-to-Rule 

**A hackathon proof-of-concept: turn a written healthcare billing policy into an executable payment-integrity check.**

Cotiviti's core business is payment accuracy - catching inappropriate claims before and after they are paid. Today, clinical and coding experts read policy documents and manually translate them into claim edits. This POC demonstrates automating that pipeline end to end:

1. **Convert** - an LLM *translates* a plain-English policy into a **structured rule** expressed
   in a small, fixed vocabulary of fields and operators (JSON).
2. **Apply** - a **deterministic Python engine** *decides* which claims violate the rule.
3. **Compare** - diff two versions of a policy and summarize the change and its claim-flagging impact.

> **Design principle:** the AI only *translates*; a deterministic, auditable engine *decides*.
> No claim is ever flagged by the model alone - every decision is reproducible and explainable,
> which is what payment integrity requires.

This maps directly onto the "Content Management in Health Care" topic (summarization of content, comparison of content changes, conversion of written policy into rules) and onto Cotiviti's Payment Policy Management work.

---

## Quick start

```bash
# 1. install
pip install -r requirements.txt

# 2. (optional) enable live AI conversion
cp .env.example .env         # then paste your ANTHROPIC_API_KEY into .env
#    without a key the app runs in OFFLINE DEMO MODE using cached sample rules

# 3. run
streamlit run app.py
```

Verify the deterministic core with no key at all:

```bash
python test_engine.py        # -> All tests passed
```

---

## What's in here

| File | Purpose |
|------|---------|
| `app.py` | Streamlit UI — three tabs: Policy→Rule, Run on claims, Compare versions |
| `engine.py` | Core logic: deterministic rule engine, policy diff, LLM conversion (+ cache fallback) |
| `test_engine.py` | Self-tests for the deterministic engine |
| `data/policies/*.txt` | Sample billing policies (5 synthetic + 1 real NCCI excerpt) |
| `data/sample_claims.csv` | 17 synthetic claim lines |
| `data/cached_rules.json` | Pre-generated rules so the demo runs offline |

## The rule schema (the "controlled vocabulary")

The LLM must emit only this shape, so the engine can execute it deterministically:

```json
{
  "rule_id": "PP-1042",
  "action": "FLAG",
  "message": "CPT 11200 exceeds the 15-unit MUE limit.",
  "combine": "all",
  "conditions": [
    {"field": "cpt_code", "op": "equals", "value": "11200"},
    {"field": "units", "op": "greater_than", "value": 15}
  ]
}
```

Allowed fields: `cpt_code, modifiers, units, member_age, member_sex, place_of_service,
provider_specialty, billed_amount, dos`. Allowed operators: `equals, not_equals, in, not_in,
greater_than, less_than, gte, lte, in_range, not_in_range, contains, not_contains, exists,
not_exists`. Any rule using a field or operator outside this list is rejected before execution.

## Demo flow 

1. **Tab 1** - load *mue_units_v1*, click **Convert to rule**, show the JSON.
2. **Tab 1** - load *real_ncci_mue_94002* (a real 2026 NCCI Policy Manual excerpt), convert it.
3. **Tab 2** - the rule flags claims out of 17; note the "$ flagged" metric.
4. **Tab 3** - compare *v1* vs *v2* (limit lowered 15 → 10): diff, AI summary, and the impact metric (flagged count rises from 2 to 3).

---

## Data & sources

Sample policies and claims are **synthetic and illustrative** - not real Cotiviti content or
protected health information. One policy (`real_ncci_mue_94002.txt`) paraphrases a real passage
from the CMS Medicare NCCI Policy Manual (effective Jan 1, 2026), Chapter I, Section V.
Source: https://www.cms.gov/files/document/2026-ncci-medicare-policy-manual-all-chapters.pdf