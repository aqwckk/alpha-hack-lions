"""Credit policy POL-01...POL-07 (reference implementation, Decimal only).

Input: a case (application, sources, state, as_of_date), the scoring result
(score, grade) and the policy config. Output: the automatic decision with
reason codes, intermediate values, offer options and, for MANUAL_REVIEW, the
policy recommendation for the underwriter.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal, localcontext

from .features import confirmed_income, months_between, parse_date
from .money import CTX, D, annuity_payment, max_amount_for_payment, money, ratio, schedule_totals

MR_ORDER = [
    "MR_PRODUCT_MANUAL_ONLY",
    "MR_AMOUNT_ABOVE_AUTO_LIMIT",
    "MR_GRAY_ZONE",
    "MR_DATA_MISMATCH",
    "MR_TAX_ARREARS_MINOR",
    "MR_INCOME_DOCUMENT_CHECK",
    "MR_COLLATERAL_REVIEW",
    "MR_RETURNED_AFTER_INFO",
]


def _s(v):
    if isinstance(v, Decimal):
        return str(v)
    return v


def _add_months(d: date, months: int) -> date:
    y = d.year + (d.month - 1 + months) // 12
    m = (d.month - 1 + months) % 12 + 1
    import calendar

    day = min(d.day, calendar.monthrange(y, m)[1])
    return date(y, m, day)


def rate_for(policy: dict, product_code: str, grade: str) -> Decimal:
    base = D(policy["products"][product_code]["base_rate_percent"])
    return money(base + D(policy["rate_premium_by_grade"][grade]))


def make_option(policy, option_type, product_code, amount, term, rate, applicant_type, recommended, payment_term=None):
    prod = policy["products"][product_code]
    totals = schedule_totals(amount, rate, payment_term or term)
    return {
        "option_type": option_type,
        "product_code": product_code,
        "amount": str(money(amount)),
        "term_months": term,
        "rate_percent": str(rate),
        "monthly_payment": str(totals["monthly_payment"]),
        "total_payment": str(totals["total_payment"]),
        "overpayment": str(totals["overpayment"]),
        "requires_owner_guarantee": applicant_type in prod["requires_owner_guarantee_for"],
        "requires_collateral": bool(prod["requires_collateral"]),
        "tranche_max_term_months": prod.get("tranche_max_term_months"),
        "recommended": recommended,
    }


def credit_line_option(policy, app, grade, business_age, allowed_payment, auto_mode: bool):
    co = policy["counter_offer"]
    line_code = co["credit_line_product"]
    line = policy["products"][line_code]
    if app["product_code"] not in co["credit_line_source_products"]:
        return None
    if app["purpose"] not in line["allowed_purposes"]:
        return None
    if business_age is None or business_age < line["min_business_age_months"]:
        return None
    if grade in line["decline_grades"] or grade in line["gray_grades"]:
        return None
    rate = rate_for(policy, line_code, grade)
    tranche = line["tranche_max_term_months"]
    limit = max_amount_for_payment(allowed_payment, rate, tranche, line["amount_max"], co["amount_rounding"])
    caps = [limit, D(app["amount"])]
    if auto_mode:
        caps.append(D(line["auto_approval_limit"]))
    limit = money(min(caps))
    if limit < D(line["amount_min"]):
        return None
    term = min(max(int(app["term_months"]), line["term_min_months"]), line["term_max_months"])
    return make_option(policy, "PRODUCT_CHANGED", line_code, limit, term, rate, app["applicant_type"], False, payment_term=tranche)


def affordability(policy, app, grade, business_age, values, auto_mode: bool) -> dict:
    """POL-06 and POL-07. auto_mode=False is the recommendation mode for manual review."""
    co = policy["counter_offer"]
    prod = policy["products"][app["product_code"]]
    amount = D(app["amount"])
    term = int(app["term_months"])
    rate = D(values["rate_percent"])
    allowed = D(values["allowed_payment"])
    requested_payment = D(values["requested_payment"])

    if requested_payment <= allowed:
        options = [make_option(policy, "REQUESTED", app["product_code"], amount, term, rate, app["applicant_type"], True)]
        codes = []
        if app["purpose"] in co["credit_line_suggest_purposes"]:
            line = credit_line_option(policy, app, grade, business_age, allowed, auto_mode)
            if line is not None:
                options.append(line)
                codes.append("CO_PRODUCT_ALTERNATIVE")
        return {"outcome": "APPROVED", "reason_codes": codes, "options": options, "rule": "POL-06"}

    options = []
    reduced = D(values["max_amount_requested_term"])
    ok = (
        reduced >= D(prod["amount_min"])
        and reduced >= amount * D(co["counter_offer_min_share"])
        and reduced < amount
        and (not auto_mode or reduced <= D(prod["auto_approval_limit"]))
    )
    if ok:
        options.append(make_option(policy, "AMOUNT_REDUCED", app["product_code"], reduced, term, rate, app["applicant_type"], False))
    for n in range(term + 1, prod["term_max_months"] + 1):
        if annuity_payment(amount, rate, n) <= allowed:
            options.append(make_option(policy, "TERM_EXTENDED", app["product_code"], amount, n, rate, app["applicant_type"], False))
            break
    line = credit_line_option(policy, app, grade, business_age, allowed, auto_mode)
    if line is not None:
        options.append(line)
    options = options[: co["max_counter_options"]]
    if not options:
        return {"outcome": "DECLINED", "reason_codes": ["DCL_AFFORDABILITY"], "options": [], "rule": "POL-07"}
    for preferred in co["recommended_priority"]:
        hit = [o for o in options if o["option_type"] == preferred]
        if hit:
            hit[0]["recommended"] = True
            break
    codes = ["CO_DEBT_LOAD"]
    if any(o["option_type"] == "PRODUCT_CHANGED" for o in options):
        codes.append("CO_PRODUCT_ALTERNATIVE")
    return {"outcome": "COUNTER_OFFER", "reason_codes": codes, "options": options, "rule": "POL-07"}


def decide(case: dict, scoring: dict, policy: dict) -> dict:
    app = case["application"]
    src = case["sources"]
    state = case.get("state") or {}
    as_of = parse_date(case["as_of_date"])
    prod = policy["products"][app["product_code"]]
    sf_cfg = policy["stop_factors"]
    grade = scoring["grade"]
    path: list[dict] = []
    details: dict = {}

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

    # POL-01 stop factors
    reg = src.get("REGISTRY") or {}
    fns = src.get("FNS") or {}
    bki = src.get("CREDIT_BUREAU") or {}
    bt = src.get("BANK_TURNOVER") or {}
    sf: list[str] = []
    business_age = None
    if not reg.get("found"):
        sf.append("SF_COMPANY_NOT_FOUND")
        details["SF_COMPANY_NOT_FOUND"] = {}
    else:
        if reg.get("company_status") in sf_cfg["blocked_company_statuses"]:
            sf.append("SF_COMPANY_STATUS")
            details["SF_COMPANY_STATUS"] = {"company_status": reg["company_status"]}
        reg_date = parse_date(reg["registration_date"])
        business_age = months_between(reg_date, as_of)
        min_age = prod["min_business_age_months"]
        if business_age < min_age:
            sf.append("SF_BUSINESS_AGE")
            details["SF_BUSINESS_AGE"] = {
                "business_age_months": business_age,
                "min_business_age_months": min_age,
                "registration_date": reg["registration_date"],
                "eligible_date": _add_months(reg_date, min_age).isoformat(),
            }
        flags = [f for f in (fns.get("unreliable_flags") or []) if f in sf_cfg["unreliable_flags"]]
        if flags:
            sf.append("SF_UNRELIABLE_REGISTRY_DATA")
            details["SF_UNRELIABLE_REGISTRY_DATA"] = {"flags": flags}
        if bki and not bki.get("no_record", True):
            days = int(bki.get("current_delinquency_days") or 0)
            if days >= sf_cfg["current_delinquency_min_days"]:
                sf.append("SF_CURRENT_DELINQUENCY")
                details["SF_CURRENT_DELINQUENCY"] = {
                    "delinquency_days": days,
                    "delinquency_amount": str(money(bki.get("current_delinquency_amount") or "0")),
                }
        arrears = money(fns.get("tax_arrears_amount") or "0")
        if arrears >= D(sf_cfg["tax_arrears_stop_amount"]):
            sf.append("SF_TAX_ARREARS")
            details["SF_TAX_ARREARS"] = {"tax_arrears_amount": str(arrears)}
        if bt.get("compliance_flag") in sf_cfg["compliance_stop_flags"]:
            sf.append("SF_COMPLIANCE")
            details["SF_COMPLIANCE"] = {"compliance_flag": bt["compliance_flag"]}
    if sf:
        path.append({"rule": "POL-01", "result": "FIRE"})
        return result("DECLINED", sf)
    path.append({"rule": "POL-01", "result": "PASS"})

    # POL-02 income confirmation
    inc_cfg = policy["income"]
    declared = money(app["monthly_revenue_declared"])
    income, source = confirmed_income(src, inc_cfg["min_turnover_months"])
    if income is None and state.get("bank_statement_attached"):
        income, source = declared, "BANK_STATEMENT"
    if income is None:
        path.append({"rule": "POL-02", "result": "FIRE"})
        if int(state.get("auto_info_request_count") or 0) < policy["process"]["max_auto_info_cycles"]:
            items = [dict(i) for i in policy["info_request_templates"]["NI_INCOME_NOT_CONFIRMED"]]
            return result("NEEDS_INFO", ["NI_INCOME_NOT_CONFIRMED"], info_items=items)
        return result("MANUAL_REVIEW", ["MR_INFO_CYCLES_EXCEEDED"])
    path.append({"rule": "POL-02", "result": "PASS"})

    # POL-03 minimal grade
    if grade in prod["decline_grades"]:
        details["DCL_LOW_SCORE"] = {"grade": grade, "product_code": app["product_code"]}
        path.append({"rule": "POL-03", "result": "FIRE"})
        return result("DECLINED", ["DCL_LOW_SCORE"])
    path.append({"rule": "POL-03", "result": "PASS"})

    # POL-04 debt load
    with localcontext(CTX):
        mismatch = ratio(declared - income, income) if source != "BANK_STATEMENT" else None
        income_for_dti = min(declared, income)
        bki_payments = money(bki.get("monthly_payments_total") or "0") if bki and not bki.get("no_record", True) else Decimal("0.00")
        existing = max(money(app["existing_monthly_payments_declared"]), bki_payments)
        max_load = D(policy["max_debt_load_by_grade"][grade])
        allowed = money(max(income_for_dti * max_load - existing, Decimal(0)))
        rate = rate_for(policy, app["product_code"], grade)
        requested_payment = annuity_payment(app["amount"], rate, int(app["term_months"]))
        max_amt = max_amount_for_payment(
            allowed, rate, int(app["term_months"]), prod["amount_max"], policy["counter_offer"]["amount_rounding"]
        )
    values = {
        "income_confirmed": _s(income),
        "income_source": source,
        "revenue_mismatch": _s(mismatch),
        "income_for_dti": _s(money(income_for_dti)),
        "existing_payments": _s(existing),
        "max_debt_load": _s(max_load),
        "allowed_payment": _s(allowed),
        "rate_percent": _s(rate),
        "requested_payment": _s(requested_payment),
        "max_amount_requested_term": _s(max_amt),
    }
    path.append({"rule": "POL-04", "result": "CALC"})

    # POL-05 manual review reasons
    mr: list[str] = []
    if prod["review_mode"] == "MANUAL":
        mr.append("MR_PRODUCT_MANUAL_ONLY")
    if prod["review_mode"] != "MANUAL" and D(app["amount"]) > D(prod["auto_approval_limit"]):
        mr.append("MR_AMOUNT_ABOVE_AUTO_LIMIT")
        details["MR_AMOUNT_ABOVE_AUTO_LIMIT"] = {"amount": str(money(app["amount"]))}
    if grade in prod["gray_grades"]:
        mr.append("MR_GRAY_ZONE")
        details["MR_GRAY_ZONE"] = {"grade": grade}
    if mismatch is not None and mismatch > D(inc_cfg["revenue_mismatch_threshold"]):
        mr.append("MR_DATA_MISMATCH")
        with localcontext(CTX):
            details["MR_DATA_MISMATCH"] = {"revenue_mismatch_pct": str((mismatch * 100).quantize(Decimal("0.01")))}
    arrears = money(fns.get("tax_arrears_amount") or "0")
    if Decimal(0) < arrears < D(sf_cfg["tax_arrears_stop_amount"]):
        mr.append("MR_TAX_ARREARS_MINOR")
        details["MR_TAX_ARREARS_MINOR"] = {"tax_arrears_amount": str(arrears)}
    if source == "BANK_STATEMENT":
        mr.append("MR_INCOME_DOCUMENT_CHECK")
    if prod["requires_collateral"]:
        coverage = ratio(app.get("collateral_value") or "0", app["amount"])
        if coverage < D(prod["min_collateral_coverage"]):
            mr.append("MR_COLLATERAL_REVIEW")
            details["MR_COLLATERAL_REVIEW"] = {"collateral_coverage": str(coverage)}
    if state.get("manual_review_required"):
        mr.append("MR_RETURNED_AFTER_INFO")
    mr = [c for c in MR_ORDER if c in mr]

    if mr:
        path.append({"rule": "POL-05", "result": "FIRE"})
        rec = affordability(policy, app, grade, business_age, values, auto_mode=False)
        recommendation = {
            "outcome": rec["outcome"],
            "reason_codes": rec["reason_codes"],
            "options": rec["options"],
            "allowed_payment": values["allowed_payment"],
            "max_amount_requested_term": values["max_amount_requested_term"],
        }
        return result("MANUAL_REVIEW", mr, values=values, recommendation=recommendation)
    path.append({"rule": "POL-05", "result": "PASS"})

    dec = affordability(policy, app, grade, business_age, values, auto_mode=True)
    if dec["rule"] == "POL-06":
        path.append({"rule": "POL-06", "result": "FIRE"})
    else:
        path.append({"rule": "POL-06", "result": "PASS"})
        path.append({"rule": "POL-07", "result": "FIRE"})
    if dec["outcome"] == "DECLINED":
        details["DCL_AFFORDABILITY"] = {"allowed_payment": values["allowed_payment"]}
    if dec["outcome"] == "COUNTER_OFFER":
        details["CO_DEBT_LOAD"] = {
            "requested_payment": values["requested_payment"],
            "allowed_payment": values["allowed_payment"],
            "grade": grade,
        }
    return result(dec["outcome"], dec["reason_codes"], values=values, options=dec["options"])
