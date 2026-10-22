"""Feature derivation from application data and source responses.

This module is the reference specification for the backend: given the same
input (see analytics/artifacts/README.md, section "case format") the backend
must derive exactly the same feature values. Pure stdlib, Decimal only.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal, localcontext

from .money import CTX, D, money, ratio


def months_between(start: date, end: date) -> int:
    """Number of full calendar months from start to end (0 if end < start)."""
    m = (end.year - start.year) * 12 + (end.month - start.month)
    if end.day < start.day:
        m -= 1
    return max(m, 0)


def parse_date(value: str) -> date:
    return date.fromisoformat(value)


def industry_group(okved_code: str | None, okved_map: dict, default_group: str) -> str | None:
    """Risk group by OKVED class: the first two digits of the code (e.g. "56.10" -> "56")."""
    if not okved_code:
        return None
    return okved_map.get(okved_code[:2], default_group)


def confirmed_income(sources: dict, min_turnover_months: int) -> tuple[Decimal | None, str | None]:
    """Monthly revenue confirmed by sources other than the client: BANK_TURNOVER, then FINANCIAL_STATEMENTS."""
    bt = sources.get("BANK_TURNOVER") or {}
    if bt.get("has_account") and int(bt.get("months_available") or 0) >= min_turnover_months:
        avg = D(bt.get("avg_monthly_inflow_12m") or "0")
        if avg > 0:
            return money(avg), "BANK_TURNOVER"
    fs = sources.get("FINANCIAL_STATEMENTS") or {}
    if fs.get("found") and fs.get("revenue") is not None and D(fs["revenue"]) > 0:
        with localcontext(CTX):
            return money(D(fs["revenue"]) / 12), "FINANCIAL_STATEMENTS"
    return None, None


def available_inflows(bt: dict) -> list[Decimal]:
    months = int(bt.get("months_available") or 0)
    values = [D(v) for v in (bt.get("inflow_by_month") or []) if v is not None]
    return values[-months:] if months else []


def compute_features(case: dict, params: dict) -> dict:
    """Return {feature_code: value or None}. None means "no data" (missing bin)."""
    app = case["application"]
    src = case["sources"]
    as_of = parse_date(case["as_of_date"])
    reg = src.get("REGISTRY") or {}
    fns = src.get("FNS") or {}
    bki = src.get("CREDIT_BUREAU") or {}
    bt = src.get("BANK_TURNOVER") or {}
    fs = src.get("FINANCIAL_STATEMENTS") or {}

    f: dict = {}

    f["business_age_months"] = (
        months_between(parse_date(reg["registration_date"]), as_of)
        if reg.get("found") and reg.get("registration_date")
        else None
    )
    f["industry_risk_group"] = industry_group(
        reg.get("okved_main_code") if reg.get("found") else None,
        params["okved_risk_groups"],
        params["okved_default_group"],
    )

    income, _ = confirmed_income(src, params["min_turnover_months"])
    f["confirmed_monthly_revenue"] = income

    growth = None
    inflows = available_inflows(bt) if bt.get("has_account") else []
    if len(inflows) >= params["min_turnover_months_for_growth"]:
        first = sum(inflows[-12:-6], Decimal(0))
        last = sum(inflows[-6:], Decimal(0))
        if first > 0:
            growth = ratio(last - first, first)
    if growth is None and fs.get("found") and fs.get("revenue_prev_year") is not None:
        prev = D(fs["revenue_prev_year"])
        if prev > 0:
            growth = ratio(D(fs["revenue"]) - prev, prev)
    f["revenue_growth"] = growth

    declared = D(app["monthly_revenue_declared"])
    declared_payments = D(app["existing_monthly_payments_declared"])
    bki_payments = D(bki.get("monthly_payments_total") or "0") if not bki.get("no_record", True) else Decimal(0)
    existing = max(declared_payments, bki_payments)
    income_for_dti = min(declared, income) if income is not None else declared
    f["debt_load_ratio"] = ratio(existing, income_for_dti) if income_for_dti > 0 else None

    has_bki = bool(bki) and not bki.get("no_record", True)
    f["bki_max_delinquency_days_12m"] = int(bki["max_delinquency_days_12m"]) if has_bki else None
    f["bki_inquiries_30d"] = int(bki["inquiries_30d"]) if has_bki else None
    f["bki_inquiries_90d"] = int(bki["inquiries_90d"]) if has_bki else None
    f["bki_credit_history_months"] = int(bki["credit_history_months"]) if has_bki else None
    f["bki_active_loans_count"] = int(bki["active_loans_count"]) if has_bki else None

    if fns:
        f["tax_arrears_flag"] = "YES" if D(fns.get("tax_arrears_amount") or "0") > 0 else "NO"
        flags = set(fns.get("unreliable_flags") or [])
        f["fns_mass_registration"] = "YES" if flags & set(params["mass_registration_flags"]) else "NO"
        f["employees_count"] = int(fns["employees_count"]) if fns.get("employees_count") is not None else None
    else:
        f["tax_arrears_flag"] = None
        f["fns_mass_registration"] = None
        f["employees_count"] = None

    vol = None
    if len(inflows) >= params["min_turnover_months"]:
        with localcontext(CTX):
            n = Decimal(len(inflows))
            mean = sum(inflows, Decimal(0)) / n
            if mean > 0:
                var = sum(((x - mean) ** 2 for x in inflows), Decimal(0)) / n
                vol = ratio(var.sqrt(), mean)
    f["turnover_volatility"] = vol

    margin = None
    if fs.get("found") and fs.get("net_profit") is not None and D(fs.get("revenue") or "0") > 0:
        margin = ratio(D(fs["net_profit"]), D(fs["revenue"]))
    f["net_margin"] = margin

    f["applicant_type"] = app["applicant_type"]
    with localcontext(CTX):
        f["requested_amount_to_revenue"] = (
            ratio(D(app["amount"]), income_for_dti * 12) if income_for_dti > 0 else None
        )
    return f
