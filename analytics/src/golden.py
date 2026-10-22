"""Golden file: expected scoring and policy results for demo profiles,
boundary cases, population picks and mock-generated profiles."""

from __future__ import annotations

import copy
from datetime import date, timedelta
from decimal import Decimal

from .demo_data import NOT_FOUND_EXAMPLE_INN, REFERENCE_DATE
from .mockgen import Rng, generate_borrower, generate_profile, generate_request, seed_for, sub_months
from .oracle.inn import complete_inn
from .oracle.money import annuity_payment, money
from .oracle.policy import decide, rate_for
from .oracle.scoring import score_case

AS_OF = REFERENCE_DATE.isoformat()
STATE0 = {"auto_info_request_count": 0, "manual_review_required": False, "bank_statement_attached": False}


def evaluate(case: dict, scorecard: dict, policy: dict) -> dict:
    sc = score_case(case, scorecard)
    dec = decide(case, sc, policy)
    return {
        "features": sc["features"],
        "score": sc["score"],
        "grade": sc["grade"],
        "pd": sc["pd"],
        "scorecard_version": sc["scorecard_version"],
        "factor_contributions": sc["factor_contributions"],
        "decision": {k: dec[k] for k in ["outcome", "mode", "reason_codes", "reason_details", "rules_path", "values",
                                         "options", "recommendation", "info_request_items", "policy_version"]},
    }


def make_case(case_id, sources, application, state=None, as_of=AS_OF, inn=None):
    return {
        "case_id": case_id,
        "as_of_date": as_of,
        "application": {**application, "applicant_inn": inn or (sources.get("REGISTRY") or {}).get("inn")},
        "state": {**STATE0, **(state or {})},
        "sources": sources,
    }


def demo_cases(companies: list[dict]) -> list[dict]:
    out = []
    for c in companies:
        for r in c["demo_requests"]:
            out.append({
                "case_id": f"DEMO-{r['request_id']}",
                "group": "demo",
                "description": c["title"] + (f" ({r['note']})" if r.get("note") else ""),
                "case": make_case(f"DEMO-{r['request_id']}", copy.deepcopy(c["sources"]), r["application"], r.get("state"), inn=c["inn"]),
            })
    return out


def boundary_cases(companies: list[dict], scorecard: dict, policy: dict) -> list[dict]:
    base_c = next(c for c in companies if c["profile_id"] == "S5")
    base_src = base_c["sources"]
    base_app = base_c["demo_requests"][0]["application"]
    ip_c = next(c for c in companies if c["profile_id"] == "S1")
    out = []

    def add(cid, desc, src_patch=None, app_patch=None, state=None, expect=None, src=None, app_base=None):
        s = copy.deepcopy(src or base_src)
        for path, value in (src_patch or {}).items():
            source, field = path.split(".", 1)
            if s[source] is None:
                s[source] = {}
            s[source][field] = value
        a = {**copy.deepcopy(app_base or base_app), **(app_patch or {})}
        out.append({"case_id": cid, "group": "boundary", "description": desc,
                    "case": make_case(cid, s, a, state, inn=s["REGISTRY"].get("inn")), "expect": expect})

    ref = REFERENCE_DATE
    add("B01", "Возраст бизнеса ровно 6 мес. (минимум EXPRESS): стоп-фактора нет",
        {"REGISTRY.registration_date": sub_months(ref, 6).isoformat()}, expect=("APPROVED", None))
    add("B02", "Возраст бизнеса 5 полных мес. (на 1 день меньше 6): SF_BUSINESS_AGE",
        {"REGISTRY.registration_date": (sub_months(ref, 6) + timedelta(days=1)).isoformat()}, expect=("DECLINED", ["SF_BUSINESS_AGE"]))
    add("B03", "Текущая просрочка 29 дней (порог 30): стоп-фактора нет",
        {"CREDIT_BUREAU.current_delinquency_days": 29, "CREDIT_BUREAU.current_delinquency_amount": "150000.00",
         "CREDIT_BUREAU.max_delinquency_days_12m": 29}, expect=(None, None))
    add("B04", "Текущая просрочка 30 дней: SF_CURRENT_DELINQUENCY",
        {"CREDIT_BUREAU.current_delinquency_days": 30, "CREDIT_BUREAU.current_delinquency_amount": "150000.00",
         "CREDIT_BUREAU.max_delinquency_days_12m": 30}, expect=("DECLINED", ["SF_CURRENT_DELINQUENCY"]))
    add("B05", "Недоимка 99 999,99 руб.: ручное рассмотрение MR_TAX_ARREARS_MINOR",
        {"FNS.tax_arrears_amount": "99999.99"}, expect=("MANUAL_REVIEW", ["MR_TAX_ARREARS_MINOR"]))
    add("B06", "Недоимка ровно 100 000,00 руб.: SF_TAX_ARREARS",
        {"FNS.tax_arrears_amount": "100000.00"}, expect=("DECLINED", ["SF_TAX_ARREARS"]))
    add("B07", "Недоимка 0,01 руб.: MR_TAX_ARREARS_MINOR", {"FNS.tax_arrears_amount": "0.01"},
        expect=("MANUAL_REVIEW", ["MR_TAX_ARREARS_MINOR"]))
    conf = Decimal(base_src["BANK_TURNOVER"]["avg_monthly_inflow_12m"])
    add("B08", "Расхождение выручки ровно 30%: ручного рассмотрения нет",
        app_patch={"monthly_revenue_declared": str(money(conf * Decimal("1.30")))}, expect=("APPROVED", None))
    add("B09", "Расхождение выручки 30,01%: MR_DATA_MISMATCH",
        app_patch={"monthly_revenue_declared": str(money(conf * Decimal("1.3001")))}, expect=("MANUAL_REVIEW", ["MR_DATA_MISMATCH"]))
    big = {"product_code": "WORKING_CAPITAL", "purpose": "CONTRACT_EXECUTION", "term_months": 36}
    add("B10", "Оборотный кредит ровно на лимит авто-полномочий 15 000 000: авторешение",
        app_patch={**big, "amount": "15000000.00"}, expect=(None, None),
        src=_scaled_turnover(base_src, 4))
    add("B11", "Оборотный кредит 15 010 000 (выше лимита авто-полномочий): MR_AMOUNT_ABOVE_AUTO_LIMIT",
        app_patch={**big, "amount": "15010000.00"}, expect=("MANUAL_REVIEW", ["MR_AMOUNT_ABOVE_AUTO_LIMIT"]),
        src=_scaled_turnover(base_src, 4))

    # payment exactly equal to the allowed payment and 1 kopeck above
    probe = make_case("probe", copy.deepcopy(base_src), base_app)
    grade = score_case(probe, scorecard)["grade"]
    rate = rate_for(policy, base_app["product_code"], grade)
    req_pay = annuity_payment(base_app["amount"], rate, base_app["term_months"])
    income = min(Decimal(base_app["monthly_revenue_declared"]), conf)
    load = Decimal(policy["max_debt_load_by_grade"][grade])
    existing_eq = money(income * load - req_pay)
    for cid, existing, exp, desc in [
        ("B12", existing_eq, ("APPROVED", None), "Запрошенный платеж ровно равен допустимому: одобрение"),
        ("B13", existing_eq + Decimal("0.01"), ("COUNTER_OFFER", None), "Допустимый платеж на 1 копейку меньше запрошенного: контрпредложение"),
    ]:
        add(cid, desc, {"CREDIT_BUREAU.monthly_payments_total": str(existing)},
            app_patch={"existing_monthly_payments_declared": str(existing)}, expect=exp)
    add("B14", "Сумма по допустимому платежу меньше 30% запрошенной: вариант AMOUNT_REDUCED не строится, есть TERM_EXTENDED и кредитная линия",
        {"CREDIT_BUREAU.monthly_payments_total": str(money(income * load - Decimal("120000")))},
        app_patch={"term_months": 6, "existing_monthly_payments_declared": "0.00"}, expect=("COUNTER_OFFER", ["CO_DEBT_LOAD", "CO_PRODUCT_ALTERNATIVE"]))
    add("B15", "Допустимый платеж 0: ни одного варианта, DCL_AFFORDABILITY",
        {"CREDIT_BUREAU.monthly_payments_total": str(money(income))}, expect=("DECLINED", ["DCL_AFFORDABILITY"]))
    no_income = {"BANK_TURNOVER.has_account": False, "BANK_TURNOVER.months_available": 0,
                 "BANK_TURNOVER.inflow_by_month": [None] * 12, "BANK_TURNOVER.avg_monthly_inflow_12m": "0.00",
                 "FINANCIAL_STATEMENTS.found": False}
    add("B16", "Нет оборотов и ГИР БО, второй автоматический дозапрос еще возможен: NEEDS_INFO",
        no_income, state={"auto_info_request_count": 2}, expect=("NEEDS_INFO", ["NI_INCOME_NOT_CONFIRMED"]))
    add("B17", "Нет подтверждения дохода, лимит автоматических дозапросов исчерпан: MR_INFO_CYCLES_EXCEEDED",
        no_income, state={"auto_info_request_count": 3}, expect=("MANUAL_REVIEW", ["MR_INFO_CYCLES_EXCEEDED"]))
    add("B18", "Доход подтвержден только выпиской клиента: MR_INCOME_DOCUMENT_CHECK",
        no_income, state={"auto_info_request_count": 1, "bank_statement_attached": True}, expect=("MANUAL_REVIEW", ["MR_INCOME_DOCUMENT_CHECK"]))
    inv = {"product_code": "INVESTMENT", "purpose": "EQUIPMENT", "amount": "40000000.00", "term_months": 60,
           "collateral_type": "EQUIPMENT"}
    add("B19", "Инвестиционный кредит, покрытие залогом 0,9999: MR_COLLATERAL_REVIEW",
        app_patch={**inv, "collateral_value": "39996000.00"}, expect=("MANUAL_REVIEW", ["MR_PRODUCT_MANUAL_ONLY", "MR_COLLATERAL_REVIEW"]),
        src=_scaled_turnover(base_src, 4))
    add("B20", "Инвестиционный кредит, покрытие залогом ровно 1,0: только MR_PRODUCT_MANUAL_ONLY",
        app_patch={**inv, "collateral_value": "40000000.00"}, expect=("MANUAL_REVIEW", ["MR_PRODUCT_MANUAL_ONLY"]),
        src=_scaled_turnover(base_src, 4))
    add("B21", "Возврат после дозапроса андеррайтера (manual_review_required): MR_RETURNED_AFTER_INFO, рекомендация APPROVED",
        state={"manual_review_required": True}, expect=("MANUAL_REVIEW", ["MR_RETURNED_AFTER_INFO"]))
    add("B22", "Субъект не найден в реестре: SF_COMPANY_NOT_FOUND",
        src=_not_found(complete_inn("009900002")), app_patch={}, expect=("DECLINED", ["SF_COMPANY_NOT_FOUND"]))
    add("B23", "Банкротство, недостоверный адрес и комплаенс-флаг: все стоп-факторы в порядке справочника",
        {"REGISTRY.company_status": "BANKRUPTCY", "FNS.unreliable_flags": ["UNRELIABLE_ADDRESS"], "BANK_TURNOVER.compliance_flag": "RED"},
        expect=("DECLINED", ["SF_COMPANY_STATUS", "SF_UNRELIABLE_REGISTRY_DATA", "SF_COMPLIANCE"]))
    add("B24", "Массовый руководитель (MASS_DIRECTOR): SF_UNRELIABLE_REGISTRY_DATA",
        {"FNS.unreliable_flags": ["MASS_DIRECTOR"]}, expect=("DECLINED", ["SF_UNRELIABLE_REGISTRY_DATA"]))
    t5 = copy.deepcopy(base_src["BANK_TURNOVER"])
    t5["inflow_by_month"] = [None] * 7 + t5["inflow_by_month"][7:]
    t5["months_available"] = 5
    t5["avg_monthly_inflow_12m"] = _avg(t5["inflow_by_month"])
    add("B25", "Обороты только за 5 мес. (минимум 6): доход берется из ГИР БО",
        {"BANK_TURNOVER." + k: v for k, v in t5.items()}, expect=(None, None))
    t6 = copy.deepcopy(base_src["BANK_TURNOVER"])
    t6["inflow_by_month"] = [None] * 6 + t6["inflow_by_month"][6:]
    t6["months_available"] = 6
    t6["avg_monthly_inflow_12m"] = _avg(t6["inflow_by_month"])
    add("B26", "Обороты ровно за 6 мес.: доход по оборотам, динамика выручки из ГИР БО",
        {"BANK_TURNOVER." + k: v for k, v in t6.items()}, expect=(None, None))
    add("B27", "Одобрение с целью SEASONAL_PURCHASES: альтернатива кредитная линия (CO_PRODUCT_ALTERNATIVE)",
        app_patch={"purpose": "SEASONAL_PURCHASES"}, expect=("APPROVED", ["CO_PRODUCT_ALTERNATIVE"]))
    add("B28", "ИП без кредитной истории (no_record): бины 'нет данных', одобрение",
        {"CREDIT_BUREAU.no_record": True}, src=copy.deepcopy(ip_c["sources"]), app_base=ip_c["demo_requests"][0]["application"],
        expect=("APPROVED", None))
    add("B29", "Возраст бизнеса 11 мес. для оборотного кредита (минимум 12): SF_BUSINESS_AGE",
        {"REGISTRY.registration_date": sub_months(ref, 11).isoformat()},
        app_patch={"product_code": "WORKING_CAPITAL", "amount": "3000000.00", "term_months": 12}, expect=("DECLINED", ["SF_BUSINESS_AGE"]))
    add("B30", "Возраст бизнеса 23 мес. для инвестиционного кредита (минимум 24): SF_BUSINESS_AGE",
        {"REGISTRY.registration_date": sub_months(ref, 23).isoformat()}, app_patch={**inv, "collateral_value": "50000000.00"},
        expect=("DECLINED", ["SF_BUSINESS_AGE"]))
    return out


def _avg(values):
    vals = [Decimal(v) for v in values if v is not None]
    return str(money(sum(vals) / len(vals)))


def _scaled_turnover(src: dict, k: int) -> dict:
    s = copy.deepcopy(src)
    t = s["BANK_TURNOVER"]
    t["inflow_by_month"] = [str(money(Decimal(v) * k)) if v is not None else None for v in t["inflow_by_month"]]
    t["avg_monthly_inflow_12m"] = _avg(t["inflow_by_month"])
    fs = s["FINANCIAL_STATEMENTS"]
    for f in ("revenue", "revenue_prev_year", "net_profit", "total_assets", "equity"):
        if fs.get(f) is not None:
            fs[f] = str(money(Decimal(fs[f]) * k))
    return s


def _not_found(inn: str) -> dict:
    from .mockgen import not_found_profile

    return not_found_profile(inn)


def population_picks(cases: list[dict], scores: list[dict], scorecard: dict, policy: dict) -> list[dict]:
    """Real synthetic applications on grade boundaries and specific policy paths."""
    out = []
    bands = [b["min_score"] for b in scorecard["grade_bands"] if b["min_score"] is not None]
    wanted = []
    for m in bands:
        wanted += [("score", m), ("score", m - 1)]
    wanted += [("path", ("EXPRESS", "DCL_LOW_SCORE")), ("path", ("WORKING_CAPITAL", "MR_GRAY_ZONE")),
               ("path", ("INVESTMENT", "DCL_LOW_SCORE")), ("path", ("INVESTMENT", "MR_GRAY_ZONE"))]
    used = set()
    for kind, target in wanted:
        for case, sc in zip(cases, scores):
            if case["case_id"] in used:
                continue
            if kind == "score":
                if sc["score"] != target:
                    continue
                dec = decide(case, sc, policy)
                if dec["outcome"] == "DECLINED" and dec["reason_codes"][0].startswith("SF_"):
                    continue
                desc = f"Синтетическая заявка с баллом ровно {target} (граница грейда)"
            else:
                prod, code = target
                if case["application"]["product_code"] != prod:
                    continue
                dec = decide(case, sc, policy)
                if code not in dec["reason_codes"]:
                    continue
                desc = f"Синтетическая заявка {prod}: путь {code} (грейд {sc['grade']})"
            used.add(case["case_id"])
            c = copy.deepcopy(case)
            c["as_of_date"] = case["as_of_date"]
            out.append({"case_id": f"P-{case['case_id']}", "group": "population", "description": desc, "case": c})
            break
    return out


def mockgen_cases(scorecard, policy) -> tuple[list[dict], list[dict]]:
    inns = [complete_inn("001234567"), complete_inn("0045678901"), complete_inn("007777777"),
            complete_inn("0088123456"), complete_inn("005000005"), NOT_FOUND_EXAMPLE_INN]
    profiles, cases = [], []
    as_of = REFERENCE_DATE
    for k, inn in enumerate(inns):
        src = generate_profile(inn, as_of)
        profiles.append({"inn": inn, "as_of_date": as_of.isoformat(), "sources": src})
        if src["REGISTRY"]["found"]:
            gen = generate_borrower(Rng(seed_for(inn)), inn, as_of)
            req = generate_request(Rng(seed_for(inn, "golden-request")), gen["sources"], gen["latent"], gen["sources"]["REGISTRY"]["applicant_type"])
        else:
            req = {"product_code": "EXPRESS", "purpose": "INVENTORY", "amount": "1000000.00", "term_months": 12,
                   "applicant_type": "LEGAL_ENTITY", "monthly_revenue_declared": "1000000.00",
                   "existing_monthly_payments_declared": "0.00", "collateral_value": None, "collateral_type": None}
        cases.append({"case_id": f"M{k + 1:02d}", "group": "mockgen",
                      "description": f"Профиль из детерминированного генератора мока для ИНН {inn}",
                      "case": make_case(f"M{k + 1:02d}", src, req, inn=inn)})
    return profiles, cases


__all__ = ["evaluate", "demo_cases", "boundary_cases", "population_picks", "mockgen_cases", "date"]
