"""Risk: the backend scoring or policy differs from the analyst's specification (63 golden cases)."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from app.config import get_settings
from app.domain import policy, scoring
from app.domain.configs import get_registry

GOLDEN = json.loads((Path(get_settings().analytics_artifacts_dir) / "expected_outcomes.json").read_text(encoding="utf-8"))
COMPARED = ("outcome", "reason_codes", "reason_details", "rules_path", "values", "options", "recommendation", "info_request_items")


def as_decimal(value):
    """Money and ratios are compared as Decimal from strings."""
    if isinstance(value, dict):
        return {k: as_decimal(v) for k, v in value.items()}
    if isinstance(value, list):
        return [as_decimal(v) for v in value]
    if isinstance(value, str):
        try:
            return Decimal(value)
        except ArithmeticError:
            return value
    return value


@pytest.fixture(scope="module")
def configs():
    registry = get_registry()
    registry.load()
    sc, pol = registry.require()
    assert (sc.version, sc.sha256) == (GOLDEN["scorecard_version"], GOLDEN["scorecard_sha256"])
    assert (pol.version, pol.sha256) == (GOLDEN["policy_version"], GOLDEN["policy_sha256"])
    return sc.content, pol.content


@pytest.mark.parametrize("case", GOLDEN["cases"], ids=[c["case_id"] for c in GOLDEN["cases"]])
def test_scoring_and_policy_match_golden(case, configs):
    scorecard, pol = configs
    expected = case["expected"]
    result = scoring.score(case["input"], scorecard)
    assert (result["score"], result["grade"], result["pd"]) == (expected["score"], expected["grade"], expected["pd"])
    assert [f["points"] for f in result["factor_contributions"]] == [f["points"] for f in expected["factor_contributions"]]
    for factor in scorecard["factors"]:
        assert as_decimal(result["features"][factor["code"]]) == as_decimal(expected["features"][factor["code"]]), factor["code"]
    decision = policy.decide(case["input"], result, pol)
    for field in COMPARED:
        assert as_decimal(decision[field]) == as_decimal(expected["decision"][field]), field
