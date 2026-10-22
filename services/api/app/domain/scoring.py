"""Scorecard: feature derivation and points (analytics/artifacts/README.md, section 3). No ML libraries.

score = base_points + sum(points of the selected bin of every factor); grade by grade_bands; pd by grade.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal, localcontext
from typing import Any

from .money import CTX, dec, money, months_between, ratio


def confirmed_income(sources: dict[str, Any], min_turnover_months: int) -> tuple[Decimal | None, str | None]:
    """Monthly revenue confirmed by a source other than the client: turnover first, then GIR BO revenue / 12."""
    turnover = sources.get("BANK_TURNOVER") or {}
    if turnover.get("has_account") and int(turnover.get("months_available") or 0) >= min_turnover_months:
        avg = dec(turnover.get("avg_monthly_inflow_12m") or "0")
        if avg > 0:
            return money(avg), "BANK_TURNOVER"
    statements = sources.get("FINANCIAL_STATEMENTS") or {}
    if statements.get("found") and statements.get("revenue") is not None and dec(statements["revenue"]) > 0:
        with localcontext(CTX):
            return money(dec(statements["revenue"]) / 12), "FINANCIAL_STATEMENTS"
    return None, None


def _inflows(turnover: dict[str, Any]) -> list[Decimal]:
    months = int(turnover.get("months_available") or 0)
    values = [dec(v) for v in (turnover.get("inflow_by_month") or []) if v is not None]
    return values[-months:] if months else []


def _bki_available(bki: dict[str, Any]) -> bool:
    return bool(bki) and not bki.get("no_record", True)


def compute_features(case: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    """Feature values; None means "no data" (the factor's missing bin)."""
    app = case["application"]
    src = case["sources"]
    as_of = date.fromisoformat(case["as_of_date"])
    reg = src.get("REGISTRY") or {}
    fns = src.get("FNS") or {}
    bki = src.get("CREDIT_BUREAU") or {}
    turnover = src.get("BANK_TURNOVER") or {}
    statements = src.get("FINANCIAL_STATEMENTS") or {}
    f: dict[str, Any] = {}

    found = bool(reg.get("found"))
    f["business_age_months"] = (
        months_between(date.fromisoformat(reg["registration_date"]), as_of) if found and reg.get("registration_date") else None
    )
    okved = reg.get("okved_main_code") if found else None
    f["industry_risk_group"] = params["okved_risk_groups"].get(okved[:2], params["okved_default_group"]) if okved else None

    income, _ = confirmed_income(src, params["min_turnover_months"])
    f["confirmed_monthly_revenue"] = income

    growth = None
    inflows = _inflows(turnover) if turnover.get("has_account") else []
    if len(inflows) >= params["min_turnover_months_for_growth"]:
        previous = sum(inflows[-12:-6], Decimal(0))
        last = sum(inflows[-6:], Decimal(0))
        if previous > 0:
            growth = ratio(last - previous, previous)
    if growth is None and statements.get("found") and statements.get("revenue_prev_year") is not None:
        prev = dec(statements["revenue_prev_year"])
        if prev > 0:
            growth = ratio(dec(statements["revenue"]) - prev, prev)
    f["revenue_growth"] = growth

    declared = dec(app["monthly_revenue_declared"])
    bki_payments = dec(bki.get("monthly_payments_total") or "0") if _bki_available(bki) else Decimal(0)
    existing = max(dec(app["existing_monthly_payments_declared"]), bki_payments)
    income_for_dti = min(declared, income) if income is not None else declared
    f["debt_load_ratio"] = ratio(existing, income_for_dti) if income_for_dti > 0 else None

    has_bki = _bki_available(bki)
    for code, key in (
        ("bki_max_delinquency_days_12m", "max_delinquency_days_12m"),
        ("bki_inquiries_30d", "inquiries_30d"),
        ("bki_inquiries_90d", "inquiries_90d"),
        ("bki_credit_history_months", "credit_history_months"),
        ("bki_active_loans_count", "active_loans_count"),
    ):
        f[code] = int(bki[key]) if has_bki else None

    if fns:
        f["tax_arrears_flag"] = "YES" if dec(fns.get("tax_arrears_amount") or "0") > 0 else "NO"
        mass = set(fns.get("unreliable_flags") or []) & set(params["mass_registration_flags"])
        f["fns_mass_registration"] = "YES" if mass else "NO"
        f["employees_count"] = int(fns["employees_count"]) if fns.get("employees_count") is not None else None
    else:
        f["tax_arrears_flag"] = f["fns_mass_registration"] = f["employees_count"] = None

    volatility = None
    if len(inflows) >= params["min_turnover_months"]:
        with localcontext(CTX):
            n = Decimal(len(inflows))
            mean = sum(inflows, Decimal(0)) / n
            if mean > 0:
                variance = sum(((x - mean) ** 2 for x in inflows), Decimal(0)) / n
                volatility = ratio(variance.sqrt(), mean)
    f["turnover_volatility"] = volatility

    margin = None
    if statements.get("found") and statements.get("net_profit") is not None and dec(statements.get("revenue") or "0") > 0:
        margin = ratio(dec(statements["net_profit"]), dec(statements["revenue"]))
    f["net_margin"] = margin

    f["applicant_type"] = app["applicant_type"]
    f["requested_amount_to_revenue"] = ratio(dec(app["amount"]), income_for_dti * 12) if income_for_dti > 0 else None
    return f


def as_json_value(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, str)):
        return value
    return str(value)


def select_bin(factor: dict[str, Any], value: Any) -> dict[str, Any]:
    if value is None:
        return factor["missing"]
    if factor["type"] == "categorical":
        return next((b for b in factor["bins"] if value in b["values"]), factor["missing"])
    x = dec(value)
    for b in factor["bins"]:
        if (b["lower"] is None or x >= dec(b["lower"])) and (b["upper"] is None or x < dec(b["upper"])):
            return b
    raise ValueError(f"value {value} of {factor['code']} is not covered by bins")


def grade_for(scorecard: dict[str, Any], score: int) -> str:
    for band in scorecard["grade_bands"]:
        if band["min_score"] is None or score >= band["min_score"]:
            return band["grade"]
    raise ValueError("grade bands do not cover the score")


def score(case: dict[str, Any], scorecard: dict[str, Any]) -> dict[str, Any]:
    features = compute_features(case, scorecard["feature_parameters"])
    total = int(scorecard["base_points"])
    contributions = []
    for factor in scorecard["factors"]:
        value = features.get(factor["code"])
        chosen = select_bin(factor, value)
        total += int(chosen["points"])
        contributions.append(
            {
                "factor_code": factor["code"],
                "factor_name": factor["name"],
                "value": as_json_value(value),
                "bin_id": chosen["id"],
                "bin_label": chosen["label"],
                "points": int(chosen["points"]),
            }
        )
    grade = grade_for(scorecard, total)
    return {
        "score": total,
        "grade": grade,
        "pd": scorecard["pd_by_grade"][grade],
        "scorecard_version": scorecard["version"],
        "features": {k: as_json_value(v) for k, v in features.items()},
        "factor_contributions": contributions,
    }
