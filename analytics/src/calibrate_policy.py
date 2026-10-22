"""Policy calibration on the synthetic application flow.

1. rate_premium_by_grade: expected-loss pricing, premium = (PD_g - PD_A) x LGD,
   rounded to 0.5 p.p.
2. max_debt_load_by_grade: variants are compared on the whole synthetic flow
   (all applications, stop factors included); the chosen variant maximises
   automatic positive decisions subject to risk constraints (see choose()).
3. Outcome shares of the chosen policy are reported per product.
"""

from __future__ import annotations

import copy
import math
from collections import Counter
from decimal import Decimal

from .oracle.policy import decide
from .oracle.scoring import score_case

LGD_UNSECURED = Decimal("0.60")
DEBT_LOAD_VARIANTS = {
    "V1": {"A": "0.25", "B": "0.20", "C": "0.17", "D": "0.14", "E": "0.10"},
    "V2": {"A": "0.30", "B": "0.25", "C": "0.20", "D": "0.15", "E": "0.10"},
    "V3": {"A": "0.35", "B": "0.30", "C": "0.25", "D": "0.18", "E": "0.12"},
    "V4": {"A": "0.40", "B": "0.35", "C": "0.30", "D": "0.20", "E": "0.15"},
}
MAX_APPROVED_DR = 0.040   # default rate of auto-positive decisions on the flow
MAX_MARGINAL_DR = 0.060   # default rate of loans newly approved by a looser variant (about the PD of grade C)
MAX_POST_LOAN_LOAD_P90 = 0.25  # 90th percentile of (existing + new payment) / income of positive decisions


def premiums(pd_by_grade: dict) -> dict:
    pa = Decimal(pd_by_grade["A"])
    out = {}
    for g, p in pd_by_grade.items():
        raw = (Decimal(p) - pa) * LGD_UNSECURED * 100
        half = (raw * 2).quantize(Decimal("1")) / 2
        out[g] = f"{max(half, Decimal(0)):.2f}"
    return out


def run_flow(cases, scores, defaults, policy) -> dict:
    outcomes = Counter()
    by_product: dict[str, Counter] = {}
    codes = Counter()
    pos_dr_n = pos_dr_bad = 0
    loads = []
    per_case = []
    for case, sc, d in zip(cases, scores, defaults):
        dec = decide(case, sc, policy)
        o = dec["outcome"]
        per_case.append(o)
        prod = case["application"]["product_code"]
        outcomes[o] += 1
        by_product.setdefault(prod, Counter())[o] += 1
        for c in dec["reason_codes"]:
            codes[c] += 1
        if o in ("APPROVED", "COUNTER_OFFER"):
            if d is not None:
                pos_dr_n += 1
                pos_dr_bad += d
            opt = next(x for x in dec["options"] if x["recommended"])
            v = dec["values"]
            load = (Decimal(v["existing_payments"]) + Decimal(opt["monthly_payment"])) / Decimal(v["income_for_dti"])
            loads.append(float(load))
    n = sum(outcomes.values())
    loads.sort()
    return {
        "n": n,
        "shares": {k: outcomes[k] / n for k in ["APPROVED", "COUNTER_OFFER", "MANUAL_REVIEW", "NEEDS_INFO", "DECLINED"]},
        "auto_positive_share": (outcomes["APPROVED"] + outcomes["COUNTER_OFFER"]) / n,
        "auto_final_share": (outcomes["APPROVED"] + outcomes["COUNTER_OFFER"] + outcomes["DECLINED"]) / n,
        "positive_dr": pos_dr_bad / pos_dr_n if pos_dr_n else None,
        "post_loan_load_p50": loads[len(loads) // 2] if loads else None,
        "post_loan_load_p90": loads[int(len(loads) * 0.9)] if loads else None,
        "by_product": {p: {k: c[k] / sum(c.values()) for k in ["APPROVED", "COUNTER_OFFER", "MANUAL_REVIEW", "NEEDS_INFO", "DECLINED"]} | {"n": sum(c.values())}
                       for p, c in sorted(by_product.items())},
        "reason_codes": dict(codes.most_common()),
        "_per_case": per_case,
    }


def calibrate(cases: list[dict], defaults_by_case: dict, scorecard: dict, base: dict) -> dict:
    policy = copy.deepcopy(base)
    policy["rate_premium_by_grade"] = premiums(scorecard["pd_by_grade"])
    scores = [score_case(c, scorecard) for c in cases]
    defaults = [defaults_by_case.get(c["case_id"]) for c in cases]
    variants = {}
    for name, dl in DEBT_LOAD_VARIANTS.items():
        p = copy.deepcopy(policy)
        p["max_debt_load_by_grade"] = dl
        variants[name] = run_flow(cases, scores, defaults, p)
    names = list(DEBT_LOAD_VARIANTS)  # from strict to loose
    chosen = names[0]
    for prev, cur in zip(names, names[1:]):
        a, b = variants[prev]["_per_case"], variants[cur]["_per_case"]
        new_ids = [k for k in range(len(cases)) if b[k] == "APPROVED" and a[k] != "APPROVED"]
        bad = sum(defaults[k] for k in new_ids)
        variants[cur]["marginal_vs_previous"] = {"n": len(new_ids), "dr": bad / len(new_ids) if new_ids else None}
        if ((new_ids and bad / len(new_ids) > MAX_MARGINAL_DR) or variants[cur]["positive_dr"] > MAX_APPROVED_DR
                or variants[cur]["post_loan_load_p90"] > MAX_POST_LOAN_LOAD_P90):
            break
        chosen = cur
    for v in variants.values():
        v.pop("_per_case")
    policy["max_debt_load_by_grade"] = DEBT_LOAD_VARIANTS[chosen]
    grade_dist = Counter(s["grade"] for s in scores)
    return {
        "policy": policy,
        "scores": scores,
        "report": {
            "lgd_unsecured": str(LGD_UNSECURED),
            "constraints": {"max_positive_dr": MAX_APPROVED_DR, "max_marginal_dr": MAX_MARGINAL_DR,
                            "max_post_loan_load_p90": MAX_POST_LOAN_LOAD_P90},
            "variants": {k: {"max_debt_load_by_grade": DEBT_LOAD_VARIANTS[k], **v} for k, v in variants.items()},
            "chosen": chosen,
            "grade_distribution_flow": {g: grade_dist[g] / len(scores) for g in "ABCDE"},
        },
    }


__all__ = ["calibrate", "premiums", "math"]
