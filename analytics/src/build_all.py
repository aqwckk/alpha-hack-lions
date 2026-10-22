"""Build every analytics artifact with one command:

    uv run --python 3.12 python -m src.build_all

Steps: synthetic population -> scorecard -> policy calibration -> demo
profiles -> golden file -> synthetic history -> report and charts. Sanity
checks fail the build if the artifacts are inconsistent.
"""

from __future__ import annotations

import hashlib
import json
import warnings
from collections import Counter
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

from .calibrate_policy import calibrate
from .config_base import FEATURE_PARAMETERS, base_policy
from .demo_data import NOT_FOUND_EXAMPLE_INN, REFERENCE_DATE, companies, users
from .golden import boundary_cases, demo_cases, evaluate, mockgen_cases, population_picks
from .history import REFERENCE_NOW, WINDOW_DAYS, build_history
from .metrics import compute_metrics
from .model import develop, psi
from .oracle.inn import inn_is_valid, ogrn_is_valid
from .oracle.money import annuity_factor, floor_to_step
from .oracle.scoring import score_case
from .plots import grade_plot, roc_plot
from .population import generate_population

ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / "artifacts"
IMG = ROOT.parent / "docs" / "analytics" / "img"
GOLDEN_VERSION = "golden-2026.10-v1"


def write_json(path: Path, data, compact_lists: tuple[str, ...] = ()):
    path.parent.mkdir(parents=True, exist_ok=True)
    if compact_lists:
        parts = ["{"]
        keys = list(data.keys())
        for i, k in enumerate(keys):
            v = data[k]
            sep = "," if i < len(keys) - 1 else ""
            if k in compact_lists:
                parts.append(f'  "{k}": [')
                parts.append(",\n".join("    " + json.dumps(x, ensure_ascii=False, separators=(",", ":")) for x in v))
                parts.append(f"  ]{sep}")
            else:
                parts.append(f'  "{k}": ' + json.dumps(v, ensure_ascii=False) + sep)
        parts.append("}")
        path.write_text("\n".join(parts) + "\n", encoding="utf-8")
    else:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check(cond: bool, msg: str):
    if not cond:
        raise SystemExit(f"SANITY CHECK FAILED: {msg}")


def main():
    warnings.filterwarnings("ignore")
    print("1/7 population")
    base = base_policy()
    pop, cases = generate_population(base, FEATURE_PARAMETERS)

    print("2/7 scorecard")
    dev = develop(pop)
    scorecard = dev["scorecard"]
    write_json(ART / "scorecard.v1.json", scorecard)

    # sanity: the pure-Python oracle reproduces the training pipeline score
    data = dev["frames"]["data"]
    by_id = {c["case_id"]: c for c in cases}
    mism = 0
    for cid, s in zip(data["case_id"].values[:3000], data["score"].values[:3000]):
        if score_case(by_id[cid], scorecard)["score"] != int(s):
            mism += 1
    check(mism == 0, f"oracle score differs from pipeline score in {mism} cases")

    print("3/7 policy calibration")
    defaults = dict(zip(pop["case_id"], pop["default"]))
    cal = calibrate(cases, defaults, scorecard, base)
    policy = cal["policy"]
    write_json(ART / "policy.v1.json", policy)

    print("4/7 demo companies and users")
    comps = companies()
    demo = demo_cases(comps)
    results = {d["case_id"]: evaluate(d["case"], scorecard, policy) for d in demo}
    check_scenarios(results, policy)
    for c in comps:
        for r in c["demo_requests"]:
            res = results[f"DEMO-{r['request_id']}"]
            d = res["decision"]
            r["expected"] = {"score": res["score"], "grade": res["grade"], "outcome": d["outcome"], "reason_codes": d["reason_codes"],
                             "options": [{k: o[k] for k in ("option_type", "product_code", "amount", "term_months", "rate_percent",
                                                            "monthly_payment", "recommended")} for o in d["options"]],
                             "recommendation_outcome": (d["recommendation"] or {}).get("outcome")}
    write_json(ART / "demo_companies.json", {
        "schema": "demo-companies", "schema_version": 1, "version": "demo-2026.10-v1",
        "reference_date": REFERENCE_DATE.isoformat(),
        "description": "Синтетические компании и ИП для демо и моков. Все ИНН с кодом региона 00, названия и ФИО вымышлены. "
                       "registration_date в sources рассчитан на reference_date; мок пересчитывает его как текущая дата минус registration_months_ago месяцев. "
                       "inflow_by_month: 12 последних полных месяцев от старого к новому, null означает месяц без данных.",
        "not_found_rule": "ИНН с цифрами 3-4, равными 99, мок возвращает как не найденный в реестре; пример: " + NOT_FOUND_EXAMPLE_INN,
        "scorecard_version": scorecard["version"], "policy_version": policy["version"],
        "companies": comps,
    })
    write_json(ART / "demo_users.json", {
        "schema": "demo-users", "schema_version": 1, "version": "demo-2026.10-v1",
        "warning": "ДЕМО: тестовые учетные записи прототипа на синтетических данных. Пароли простые и публичные, использовать только в демо-окружении. В БД хранить только хеш пароля.",
        "users": users(comps),
    })

    print("5/7 golden file")
    bcases = boundary_cases(comps, scorecard, policy)
    pcases = population_picks(cases, cal["scores"], scorecard, policy)
    profiles, mcases = mockgen_cases(scorecard, policy)
    golden = []
    for item in demo + bcases + pcases + mcases:
        res = evaluate(item["case"], scorecard, policy)
        exp = item.get("expect")
        if exp:
            outcome, codes = exp
            if outcome:
                check(res["decision"]["outcome"] == outcome, f"{item['case_id']}: outcome {res['decision']['outcome']} != {outcome}")
            if codes:
                check(res["decision"]["reason_codes"] == codes, f"{item['case_id']}: codes {res['decision']['reason_codes']} != {codes}")
        golden.append({"case_id": item["case_id"], "group": item["group"], "description": item["description"],
                       "input": {k: item["case"][k] for k in ("as_of_date", "application", "state", "sources")}, "expected": res})
    write_json(ART / "expected_outcomes.json", {
        "schema": "expected-outcomes", "schema_version": 1, "version": GOLDEN_VERSION,
        "scorecard_version": scorecard["version"], "policy_version": policy["version"],
        "scorecard_sha256": sha256_file(ART / "scorecard.v1.json"), "policy_sha256": sha256_file(ART / "policy.v1.json"),
        "compare": "Бэкенд сравнивает: expected.score, expected.grade, expected.pd, expected.features (обязательно для кодов факторов карты, остальные признаки справочные), expected.factor_contributions[].points, "
                   "expected.decision.outcome, reason_codes, rules_path, values, options, recommendation, info_request_items. "
                   "Денежные значения сравниваются как Decimal из строк.",
        "mock_profiles": profiles,
        "cases": golden,
    })

    print("6/7 synthetic history")
    hist = build_history(scorecard, policy)
    start = (REFERENCE_NOW - timedelta(days=WINDOW_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    end = REFERENCE_NOW.strftime("%Y-%m-%dT%H:%M:%SZ")
    m90 = compute_metrics(hist["events"], start, end,
                          policy["process"]["decision_sla_auto_minutes"] * 60, policy["process"]["decision_sla_manual_hours"] * 3600)
    start30 = (REFERENCE_NOW - timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
    m30 = compute_metrics(hist["events"], start30, end,
                          policy["process"]["decision_sla_auto_minutes"] * 60, policy["process"]["decision_sla_manual_hours"] * 3600)
    write_json(ART / "synthetic_applications.json", {
        "schema": "synthetic-history", "schema_version": 1, "version": "history-2026.10-v1",
        "reference_now": end, "window_days": WINDOW_DAYS,
        "description": "Исторический поток синтетических заявок для экрана метрик (BK-06). При загрузке сдвиньте все отметки времени на (текущее время минус reference_now). "
                       "client_login вида hist.client.NNN: неактивные синтетические клиенты без пароля.",
        "scorecard_version": scorecard["version"], "policy_version": policy["version"],
        "applications": hist["applications"], "events": hist["events"],
    }, compact_lists=("applications", "events"))
    hist_grades = [a["grade"] for a in hist["applications"] if a["grade"]]
    import pandas as pd

    dev_all = pd.concat([dev["frames"]["train"], dev["frames"]["test"]])
    psi_hist = psi(dev_all["grade"], pd.Series(hist_grades))

    print("7/7 report and charts")
    IMG.mkdir(parents=True, exist_ok=True)
    roc_plot(dev["frames"], dev["report"]["metrics"], IMG / "roc_gini.png")
    grade_plot(dev["report"]["grades"], IMG / "grades_calibration.png")
    demo_table = [{"case_id": k, "score": v["score"], "grade": v["grade"], "outcome": v["decision"]["outcome"],
                   "reason_codes": v["decision"]["reason_codes"],
                   "values": v["decision"]["values"],
                   "options": [(o["option_type"], o["amount"], o["term_months"], o["rate_percent"], o["monthly_payment"], o["recommended"])
                               for o in (v["decision"]["options"] or (v["decision"]["recommendation"] or {}).get("options", []))]}
                  for k, v in results.items()]
    report = {
        "model": dev["report"],
        "policy_calibration": cal["report"],
        "history": {"applications": len(hist["applications"]), "events": len(hist["events"]),
                    "event_types": dict(Counter(e["event_type"] for e in hist["events"]).most_common()),
                    "metrics_90d": m90, "metrics_30d": m30, "psi_grade_dev_vs_history": psi_hist},
        "demo": demo_table,
        "golden": {"cases": len(golden), "by_group": dict(Counter(g["group"] for g in golden))},
    }
    write_json(ART / "build_report.json", report)

    # final consistency checks
    for c in comps:
        check(inn_is_valid(c["inn"]) and ogrn_is_valid(c["sources"]["REGISTRY"]["ogrn"]), f"bad INN/OGRN {c['inn']}")
    check(len({c["inn"] for c in comps}) == len(comps), "duplicate INN")
    check(300 <= len(hist["applications"]) <= 500, "history size")
    print(json.dumps({"gini": {k: round(v["gini"], 3) for k, v in dev["report"]["metrics"].items()},
                      "psi_score": round(dev["report"]["psi"]["score_deciles"], 4),
                      "chosen_debt_load": cal["report"]["chosen"], "golden_cases": len(golden),
                      "history_apps": len(hist["applications"]), "history_events": len(hist["events"])}, ensure_ascii=False))
    print("OK")


def check_scenarios(results: dict, policy: dict):
    def d(cid):
        return results[cid]["decision"]

    p = policy["products"]
    s1 = results["DEMO-S1"]
    check(d("DEMO-S1")["outcome"] == "APPROVED" and s1["grade"] in p["EXPRESS"]["green_grades"], f"S1: {d('DEMO-S1')['outcome']} {s1['grade']}")
    check([r["rule"] for r in d("DEMO-S1")["rules_path"] if r["result"] == "FIRE"] == ["POL-06"], "S1 path")
    s2 = results["DEMO-S2"]
    types = [o["option_type"] for o in d("DEMO-S2")["options"]]
    check(d("DEMO-S2")["outcome"] == "COUNTER_OFFER" and types == ["AMOUNT_REDUCED", "TERM_EXTENDED", "PRODUCT_CHANGED"], f"S2: {d('DEMO-S2')['outcome']} {types}")
    check(s2["grade"] in p["WORKING_CAPITAL"]["green_grades"] and s2["grade"] in p["CREDIT_LINE"]["green_grades"], "S2 grade")
    te = next(o for o in d("DEMO-S2")["options"] if o["option_type"] == "TERM_EXTENDED")
    check(te["term_months"] <= 36 and te["recommended"], "S2 term extended")
    line = next(o for o in d("DEMO-S2")["options"] if o["option_type"] == "PRODUCT_CHANGED")
    check(Decimal(line["amount"]) >= Decimal("1000000"), "S2 line limit")
    s3 = d("DEMO-S3")
    check(s3["outcome"] == "MANUAL_REVIEW" and s3["reason_codes"] == ["MR_PRODUCT_MANUAL_ONLY", "MR_DATA_MISMATCH"], f"S3: {s3['reason_codes']}")
    check(results["DEMO-S3"]["grade"] not in p["INVESTMENT"]["decline_grades"], "S3 grade")
    v = s3["values"]
    check(Decimal(v["max_amount_requested_term"]) < Decimal("40000000"), "S3 max by confirmed revenue must be < 40M")
    declared = Decimal(results["DEMO-S3"]["features"]["confirmed_monthly_revenue"]) * Decimal("1.35")
    allowed_decl = declared * Decimal(v["max_debt_load"]) - Decimal(v["existing_payments"])
    check(floor_to_step(allowed_decl * annuity_factor(v["rate_percent"], 60), 10000) >= Decimal("40000000"), "S3 max by declared revenue must be >= 40M")
    check("MR_RETURNED_AFTER_INFO" in d("DEMO-S3-AFTER-INFO")["reason_codes"], "S3 after info")
    check(d("DEMO-S4")["reason_codes"] == ["SF_BUSINESS_AGE", "SF_CURRENT_DELINQUENCY"], f"S4: {d('DEMO-S4')['reason_codes']}")
    check(d("DEMO-S5")["outcome"] == "APPROVED", f"S5: {d('DEMO-S5')['outcome']}")
    check(d("DEMO-X1")["reason_codes"] == ["SF_COMPANY_STATUS"], "X1")
    check(d("DEMO-X2")["reason_codes"] == ["SF_TAX_ARREARS"], "X2")
    check(d("DEMO-X3-WC-12M")["outcome"] == "APPROVED" and d("DEMO-X3-WC-12M")["reason_codes"] == ["CO_PRODUCT_ALTERNATIVE"], f"X3-12M {d('DEMO-X3-WC-12M')['outcome']} {d('DEMO-X3-WC-12M')['reason_codes']}")
    check(d("DEMO-X3-WC-25M")["reason_codes"] == ["MR_AMOUNT_ABOVE_AUTO_LIMIT"], f"X3-25M {d('DEMO-X3-WC-25M')['reason_codes']}")
    check(d("DEMO-X4")["outcome"] == "APPROVED", f"X4 {d('DEMO-X4')['outcome']} {results['DEMO-X4']['grade']}")
    check(d("DEMO-X5")["reason_codes"] == ["NI_INCOME_NOT_CONFIRMED"], "X5")
    check(d("DEMO-X5-WITH-STATEMENT")["reason_codes"] == ["MR_INCOME_DOCUMENT_CHECK"], f"X5 statement {d('DEMO-X5-WITH-STATEMENT')['reason_codes']}")
    check(d("DEMO-X6")["reason_codes"] == ["DCL_LOW_SCORE"], f"X6 {d('DEMO-X6')['reason_codes']} {results['DEMO-X6']['grade']}")
    check(d("DEMO-X7")["reason_codes"] == ["SF_COMPLIANCE"], "X7")


if __name__ == "__main__":
    main()
