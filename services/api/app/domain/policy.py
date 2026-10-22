"""Credit policy POL-01...POL-07 (decision-model.md, analytics/artifacts/README.md section 4.1).

The policy never computes the score: it takes the grade from scoring and turns it into an outcome
with reason codes, intermediate values, offer options and, for manual review, a recommendation.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal, localcontext
from typing import Any

from .money import (
    CTX,
    add_months,
    annuity_payment,
    dec,
    max_amount_for_payment,
    money,
    months_between,
    ratio,
    totals,
)
from .scoring import confirmed_income


def rate_for(policy: dict[str, Any], product_code: str, grade: str) -> Decimal:
    return money(dec(policy["products"][product_code]["base_rate_percent"]) + dec(policy["rate_premium_by_grade"][grade]))


def build_option(
    policy: dict[str, Any],
    option_type: str,
    product_code: str,
    amount: Decimal,
    term: int,
    rate: Decimal,
    applicant_type: str,
    recommended: bool,
    payment_term: int | None = None,
) -> dict[str, Any]:
    product = policy["products"][product_code]
    t = totals(amount, rate, payment_term or term)
    return {
        "option_type": option_type,
        "product_code": product_code,
        "amount": str(money(amount)),
        "term_months": term,
        "rate_percent": str(rate),
        "monthly_payment": str(t["monthly_payment"]),
        "total_payment": str(t["total_payment"]),
        "overpayment": str(t["overpayment"]),
        "requires_owner_guarantee": applicant_type in product["requires_owner_guarantee_for"],
        "requires_collateral": bool(product["requires_collateral"]),
        "tranche_max_term_months": product.get("tranche_max_term_months"),
        "recommended": recommended,
    }


def credit_line_option(policy, app, grade, business_age, allowed_payment, auto_mode: bool) -> dict[str, Any] | None:
    co = policy["counter_offer"]
    line_code = co["credit_line_product"]
    line = policy["products"][line_code]
    if app["product_code"] not in co["credit_line_source_products"] or app["purpose"] not in line["allowed_purposes"]:
        return None
    if business_age is None or business_age < line["min_business_age_months"]:
        return None
    if grade in line["decline_grades"] or grade in line["gray_grades"]:
        return None
    rate = rate_for(policy, line_code, grade)
    tranche = line["tranche_max_term_months"]
    caps = [
        max_amount_for_payment(allowed_payment, rate, tranche, line["amount_max"], co["amount_rounding"]),
        dec(app["amount"]),
    ]
    if auto_mode:
        caps.append(dec(line["auto_approval_limit"]))
    limit = money(min(caps))
    if limit < dec(line["amount_min"]):
        return None
    term = min(max(int(app["term_months"]), line["term_min_months"]), line["term_max_months"])
    return build_option(policy, "PRODUCT_CHANGED", line_code, limit, term, rate, app["applicant_type"], False, payment_term=tranche)


def affordability(policy, app, grade, business_age, values, auto_mode: bool) -> dict[str, Any]:
    """POL-06 (approve) or POL-07 (counter offer); auto_mode=False is the recommendation mode."""
    co = policy["counter_offer"]
    product = policy["products"][app["product_code"]]
    amount, term = dec(app["amount"]), int(app["term_months"])
    rate, allowed = dec(values["rate_percent"]), dec(values["allowed_payment"])

    if dec(values["requested_payment"]) <= allowed:
        options = [build_option(policy, "REQUESTED", app["product_code"], amount, term, rate, app["applicant_type"], True)]
        codes: list[str] = []
        if app["purpose"] in co["credit_line_suggest_purposes"]:
            line = credit_line_option(policy, app, grade, business_age, allowed, auto_mode)
            if line is not None:
                options.append(line)
                codes.append("CO_PRODUCT_ALTERNATIVE")
        return {"outcome": "APPROVED", "reason_codes": codes, "options": options, "rule": "POL-06"}

    built: dict[str, dict[str, Any]] = {}
    reduced = dec(values["max_amount_requested_term"])
    if (
        reduced >= dec(product["amount_min"])
        and reduced >= amount * dec(co["counter_offer_min_share"])
        and reduced < amount
        and (not auto_mode or reduced <= dec(product["auto_approval_limit"]))
    ):
        built["AMOUNT_REDUCED"] = build_option(policy, "AMOUNT_REDUCED", app["product_code"], reduced, term, rate, app["applicant_type"], False)
    for n in range(term + 1, product["term_max_months"] + 1):
        if annuity_payment(amount, rate, n) <= allowed:
            built["TERM_EXTENDED"] = build_option(policy, "TERM_EXTENDED", app["product_code"], amount, n, rate, app["applicant_type"], False)
            break
    line = credit_line_option(policy, app, grade, business_age, allowed, auto_mode)
    if line is not None:
        built["PRODUCT_CHANGED"] = line
    options = [built[t] for t in co["option_order"] if t in built][: co["max_counter_options"]]
    if not options:
        return {"outcome": "DECLINED", "reason_codes": ["DCL_AFFORDABILITY"], "options": [], "rule": "POL-07"}
    for preferred in co["recommended_priority"]:
        hit = next((o for o in options if o["option_type"] == preferred), None)
        if hit:
            hit["recommended"] = True
            break
    codes = ["CO_DEBT_LOAD"]
    if any(o["option_type"] == "PRODUCT_CHANGED" for o in options):
        codes.append("CO_PRODUCT_ALTERNATIVE")
    return {"outcome": "COUNTER_OFFER", "reason_codes": codes, "options": options, "rule": "POL-07"}


def _rule_codes(policy: dict[str, Any], rule_id: str) -> list[str]:
    return next(r["reason_codes"] for r in policy["rules"] if r["id"] == rule_id)


def decide(case: dict[str, Any], scoring: dict[str, Any], policy: dict[str, Any]) -> dict[str, Any]:
    app, src = case["application"], case["sources"]
    state = case.get("state") or {}
    as_of = date.fromisoformat(case["as_of_date"])
    product = policy["products"][app["product_code"]]
    stop = policy["stop_factors"]
    grade = scoring["grade"]
    path: list[dict[str, str]] = []
    details: dict[str, dict[str, Any]] = {}

    def result(outcome, codes, values=None, options=None, recommendation=None, info_items=None):
        return {
            "outcome": outcome,
            "mode": "AUTO",
            "reason_codes": codes,
            "reason_details": {c: details[c] for c in codes if c in details},
            "rules_path": path,
            "values": values,
            "options": options or [],
            "recommendation": recommendation,
            "info_request_items": info_items or [],
            "policy_version": policy["version"],
            "scorecard_version": scoring["scorecard_version"],
            "grade": grade,
            "score": scoring["score"],
        }

    reg = src.get("REGISTRY") or {}
    fns = src.get("FNS") or {}
    bki = src.get("CREDIT_BUREAU") or {}
    turnover = src.get("BANK_TURNOVER") or {}

    # POL-01: stop factors (all fired codes are collected)
    fired: list[str] = []
    business_age = None
    if not reg.get("found"):
        fired.append("SF_COMPANY_NOT_FOUND")
        details["SF_COMPANY_NOT_FOUND"] = {}
    else:
        if reg.get("company_status") in stop["blocked_company_statuses"]:
            fired.append("SF_COMPANY_STATUS")
            details["SF_COMPANY_STATUS"] = {"company_status": reg["company_status"]}
        registered = date.fromisoformat(reg["registration_date"])
        business_age = months_between(registered, as_of)
        if business_age < product["min_business_age_months"]:
            fired.append("SF_BUSINESS_AGE")
            details["SF_BUSINESS_AGE"] = {
                "business_age_months": business_age,
                "min_business_age_months": product["min_business_age_months"],
                "registration_date": reg["registration_date"],
                "eligible_date": add_months(registered, product["min_business_age_months"]).isoformat(),
            }
        flags = [f for f in (fns.get("unreliable_flags") or []) if f in stop["unreliable_flags"]]
        if flags:
            fired.append("SF_UNRELIABLE_REGISTRY_DATA")
            details["SF_UNRELIABLE_REGISTRY_DATA"] = {"flags": flags}
        if bki and not bki.get("no_record", True):
            days = int(bki.get("current_delinquency_days") or 0)
            if days >= stop["current_delinquency_min_days"]:
                fired.append("SF_CURRENT_DELINQUENCY")
                details["SF_CURRENT_DELINQUENCY"] = {
                    "delinquency_days": days,
                    "delinquency_amount": str(money(bki.get("current_delinquency_amount") or "0")),
                }
        arrears = money(fns.get("tax_arrears_amount") or "0")
        if arrears >= dec(stop["tax_arrears_stop_amount"]):
            fired.append("SF_TAX_ARREARS")
            details["SF_TAX_ARREARS"] = {"tax_arrears_amount": str(arrears)}
        if turnover.get("compliance_flag") in stop["compliance_stop_flags"]:
            fired.append("SF_COMPLIANCE")
            details["SF_COMPLIANCE"] = {"compliance_flag": turnover["compliance_flag"]}
    if fired:
        path.append({"rule": "POL-01", "result": "FIRE"})
        return result("DECLINED", fired)
    path.append({"rule": "POL-01", "result": "PASS"})

    # POL-02: income confirmation
    income_cfg = policy["income"]
    declared = money(app["monthly_revenue_declared"])
    income, source = confirmed_income(src, income_cfg["min_turnover_months"])
    if income is None and state.get("bank_statement_attached"):
        income, source = declared, "BANK_STATEMENT"
    if income is None:
        path.append({"rule": "POL-02", "result": "FIRE"})
        if int(state.get("auto_info_request_count") or 0) < policy["process"]["max_auto_info_cycles"]:
            items = [dict(i) for i in policy["info_request_templates"]["NI_INCOME_NOT_CONFIRMED"]]
            return result("NEEDS_INFO", ["NI_INCOME_NOT_CONFIRMED"], info_items=items)
        return result("MANUAL_REVIEW", ["MR_INFO_CYCLES_EXCEEDED"])
    path.append({"rule": "POL-02", "result": "PASS"})

    # POL-03: minimal grade
    if grade in product["decline_grades"]:
        details["DCL_LOW_SCORE"] = {"grade": grade, "product_code": app["product_code"]}
        path.append({"rule": "POL-03", "result": "FIRE"})
        return result("DECLINED", ["DCL_LOW_SCORE"])
    path.append({"rule": "POL-03", "result": "PASS"})

    # POL-04: debt load (no outcome)
    with localcontext(CTX):
        mismatch = ratio(declared - income, income) if source != "BANK_STATEMENT" else None
        income_for_dti = min(declared, income)
        bki_payments = money(bki.get("monthly_payments_total") or "0") if bki and not bki.get("no_record", True) else money(0)
        existing = max(money(app["existing_monthly_payments_declared"]), bki_payments)
        max_load = dec(policy["max_debt_load_by_grade"][grade])
        allowed = money(max(income_for_dti * max_load - existing, Decimal(0)))
        rate = rate_for(policy, app["product_code"], grade)
        requested_payment = annuity_payment(app["amount"], rate, int(app["term_months"]))
        max_amount = max_amount_for_payment(
            allowed, rate, int(app["term_months"]), product["amount_max"], policy["counter_offer"]["amount_rounding"]
        )
    values = {
        "income_confirmed": str(income),
        "income_source": source,
        "revenue_mismatch": None if mismatch is None else str(mismatch),
        "income_for_dti": str(money(income_for_dti)),
        "existing_payments": str(existing),
        "max_debt_load": str(max_load),
        "allowed_payment": str(allowed),
        "rate_percent": str(rate),
        "requested_payment": str(requested_payment),
        "max_amount_requested_term": str(max_amount),
    }
    path.append({"rule": "POL-04", "result": "CALC"})

    # POL-05: reasons for manual review (all collected, ordered as in the reason dictionary of the rule)
    reasons: set[str] = set()
    if product["review_mode"] == "MANUAL":
        reasons.add("MR_PRODUCT_MANUAL_ONLY")
    elif dec(app["amount"]) > dec(product["auto_approval_limit"]):
        reasons.add("MR_AMOUNT_ABOVE_AUTO_LIMIT")
        details["MR_AMOUNT_ABOVE_AUTO_LIMIT"] = {"amount": str(money(app["amount"]))}
    if grade in product["gray_grades"]:
        reasons.add("MR_GRAY_ZONE")
        details["MR_GRAY_ZONE"] = {"grade": grade}
    if mismatch is not None and mismatch > dec(income_cfg["revenue_mismatch_threshold"]):
        reasons.add("MR_DATA_MISMATCH")
        with localcontext(CTX):
            details["MR_DATA_MISMATCH"] = {"revenue_mismatch_pct": str((mismatch * 100).quantize(Decimal("0.01")))}
    arrears = money(fns.get("tax_arrears_amount") or "0")
    if Decimal(0) < arrears < dec(stop["tax_arrears_stop_amount"]):
        reasons.add("MR_TAX_ARREARS_MINOR")
        details["MR_TAX_ARREARS_MINOR"] = {"tax_arrears_amount": str(arrears)}
    if source == "BANK_STATEMENT":
        reasons.add("MR_INCOME_DOCUMENT_CHECK")
    if product["requires_collateral"]:
        coverage = ratio(app.get("collateral_value") or "0", app["amount"])
        if coverage < dec(product["min_collateral_coverage"]):
            reasons.add("MR_COLLATERAL_REVIEW")
            details["MR_COLLATERAL_REVIEW"] = {"collateral_coverage": str(coverage)}
    if state.get("manual_review_required"):
        reasons.add("MR_RETURNED_AFTER_INFO")
    ordered = [c for c in _rule_codes(policy, "POL-05") if c in reasons]
    if ordered:
        path.append({"rule": "POL-05", "result": "FIRE"})
        rec = affordability(policy, app, grade, business_age, values, auto_mode=False)
        recommendation = {
            "outcome": rec["outcome"],
            "reason_codes": rec["reason_codes"],
            "options": rec["options"],
            "allowed_payment": values["allowed_payment"],
            "max_amount_requested_term": values["max_amount_requested_term"],
        }
        return result("MANUAL_REVIEW", ordered, values=values, recommendation=recommendation)
    path.append({"rule": "POL-05", "result": "PASS"})

    # POL-06 / POL-07
    dec_result = affordability(policy, app, grade, business_age, values, auto_mode=True)
    if dec_result["rule"] == "POL-06":
        path.append({"rule": "POL-06", "result": "FIRE"})
    else:
        path.append({"rule": "POL-06", "result": "PASS"})
        path.append({"rule": "POL-07", "result": "FIRE"})
    if dec_result["outcome"] == "DECLINED":
        details["DCL_AFFORDABILITY"] = {"allowed_payment": values["allowed_payment"]}
    elif dec_result["outcome"] == "COUNTER_OFFER":
        details["CO_DEBT_LOAD"] = {
            "requested_payment": values["requested_payment"],
            "allowed_payment": values["allowed_payment"],
            "grade": grade,
        }
    return result(dec_result["outcome"], dec_result["reason_codes"], values=values, options=dec_result["options"])
