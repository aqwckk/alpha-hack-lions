"""Scorecard application: score = base_points + sum of bin points. No ML libraries."""

from __future__ import annotations

from decimal import Decimal

from .features import compute_features
from .money import D


def _fmt(value) -> str | int | None:
    if value is None or isinstance(value, (int, str)):
        return value
    return str(value)


def find_bin(factor: dict, value) -> dict:
    if value is None:
        return factor["missing"]
    if factor["type"] == "categorical":
        for b in factor["bins"]:
            if value in b["values"]:
                return b
        return factor["missing"]
    x = D(value)
    for b in factor["bins"]:
        lo = b["lower"]
        hi = b["upper"]
        if (lo is None or x >= D(lo)) and (hi is None or x < D(hi)):
            return b
    raise ValueError(f"value {value} of {factor['code']} is not covered by bins")


def grade_for_score(scorecard: dict, score: int) -> str:
    for band in scorecard["grade_bands"]:
        if band["min_score"] is None or score >= band["min_score"]:
            return band["grade"]
    raise ValueError("grade bands do not cover the score")


def score_case(case: dict, scorecard: dict) -> dict:
    features = compute_features(case, scorecard["feature_parameters"])
    contributions = []
    total = int(scorecard["base_points"])
    for factor in scorecard["factors"]:
        value = features.get(factor["code"])
        b = find_bin(factor, value)
        total += int(b["points"])
        contributions.append(
            {
                "factor_code": factor["code"],
                "factor_name": factor["name"],
                "value": _fmt(value),
                "bin_id": b["id"],
                "bin_label": b["label"],
                "points": int(b["points"]),
            }
        )
    grade = grade_for_score(scorecard, total)
    return {
        "score": total,
        "grade": grade,
        "pd": scorecard["pd_by_grade"][grade],
        "scorecard_version": scorecard["version"],
        "features": {k: _fmt(v) for k, v in features.items()},
        "factor_contributions": contributions,
    }


def score_value_only(features: dict, scorecard: dict) -> int:
    total = int(scorecard["base_points"])
    for factor in scorecard["factors"]:
        total += int(find_bin(factor, features.get(factor["code"]))["points"])
    return total


__all__ = ["score_case", "find_bin", "grade_for_score", "score_value_only", "Decimal"]
