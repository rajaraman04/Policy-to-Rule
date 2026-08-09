import json
from pathlib import Path

import engine

claims = engine.load_claims()
rules = json.loads(Path("data/cached_rules.json").read_text())["rules"]

EXPECTED = {
    "mue_units_v1": {"CLM0001", "CLM0014"},
    "mue_units_v2": {"CLM0001", "CLM0003", "CLM0014"},
    "age_edit": {"CLM0004", "CLM0006"},
    "modifier_edit": {"CLM0007"},
    "pos_edit": {"CLM0010", "CLM0012"},
    "real_ncci_mue_94002": {"CLM0016"},
    "clinical_guideline_crc": {"CLM0018"},
}


def test_rules_flag_expected_claims():
    for stem, rule in rules.items():
        assert not engine.validate_rule(rule), f"{stem} invalid: {engine.validate_rule(rule)}"
        flagged = {r["claim"]["claim_id"] for r in engine.apply_rule(rule, claims) if r["matched"]}
        assert flagged == EXPECTED[stem], f"{stem}: got {flagged}, expected {EXPECTED[stem]}"


def test_operators():
    row = {"units": "12", "modifiers": "25|50", "member_age": "45"}
    assert engine.evaluate_condition(row, {"field": "units", "op": "greater_than", "value": 10})
    assert engine.evaluate_condition(row, {"field": "modifiers", "op": "contains", "value": "50"})
    assert engine.evaluate_condition(row, {"field": "member_age", "op": "not_in_range", "value": [18, 39]})
    assert not engine.evaluate_condition(row, {"field": "units", "op": "less_than", "value": 5})


def test_version_change_increases_flags():
    v1 = {r["claim"]["claim_id"] for r in engine.apply_rule(rules["mue_units_v1"], claims) if r["matched"]}
    v2 = {r["claim"]["claim_id"] for r in engine.apply_rule(rules["mue_units_v2"], claims) if r["matched"]}
    assert v1 < v2, "tighter v2 limit should flag a superset of v1"


if __name__ == "__main__":
    test_rules_flag_expected_claims()
    test_operators()
    test_version_change_increases_flags()
    print("All tests passed")