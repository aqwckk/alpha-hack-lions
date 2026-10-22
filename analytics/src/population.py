"""Synthetic population of SME borrowers with a hidden default process.

Two time cohorts (applications of 2024H2 and 2025H1, 12-month performance
window) are generated with the same process as the mock (src.mockgen), the
second one with a small drift. The default flag comes from a hidden logit of
true characteristics plus noise; the analyst model never sees the logit.
"""

from __future__ import annotations

import math
from datetime import date, timedelta

import numpy as np
import pandas as pd

from .mockgen import Rng, generate_borrower, generate_request, seed_for
from .oracle.features import compute_features
from .oracle.inn import complete_inn

SEED = 20261023
BASE_RATES = {"EXPRESS": 22.0, "WORKING_CAPITAL": 19.0, "INVESTMENT": 17.0}
COHORTS = [
    {"name": "2024H2", "start": date(2024, 7, 1), "days": 184, "n": 8000, "drift": 0.0},
    {"name": "2025H1", "start": date(2025, 1, 1), "days": 181, "n": 4000, "drift": 1.0},
]
NUMERIC_FEATURES = [
    "business_age_months",
    "confirmed_monthly_revenue",
    "revenue_growth",
    "debt_load_ratio",
    "bki_max_delinquency_days_12m",
    "bki_inquiries_30d",
    "bki_inquiries_90d",
    "bki_credit_history_months",
    "bki_active_loans_count",
    "turnover_volatility",
    "net_margin",
    "employees_count",
    "requested_amount_to_revenue",
]
CATEGORICAL_FEATURES = ["industry_risk_group", "tax_arrears_flag", "fns_mass_registration", "applicant_type"]


def synthetic_inn(i: int, is_ip: bool) -> str:
    """Region "00", inspection 01..98 (99 is reserved for "not found")."""
    insp = i % 98 + 1
    if is_ip:
        return complete_inn(f"00{insp:02d}{i:06d}")
    return complete_inn(f"00{insp:02d}{i:05d}")


def hidden_logit(f: dict, lat: dict, sources: dict, req: dict, cohort_shift: float, noise: float) -> float:
    """The "true" default process. Not visible to the model."""
    x = -4.9 + cohort_shift
    x += -0.35 * lat["q"]
    age = f["business_age_months"] or 0
    x += 0.8 if age < 12 else 0.4 if age < 24 else (-0.25 if age > 60 else 0.0)
    x += {"HIGH": 0.45, "MEDIUM": 0.1, "LOW": -0.2}[lat["industry_group"]]
    x += -2.5 * lat["growth"]
    x += 2.0 * (lat["sigma"] - 0.15)
    dl = float(f["debt_load_ratio"]) if f["debt_load_ratio"] is not None else 0.0
    x += 5.0 * min(dl, 0.8)
    bki = sources["CREDIT_BUREAU"]
    if bki.get("no_record"):
        x += 0.35
    else:
        d = bki["max_delinquency_days_12m"]
        x += 1.6 if d >= 60 else 1.1 if d >= 30 else 0.5 if d >= 1 else 0.0
        x += 0.12 * min(bki["inquiries_90d"], 10)
        x += 0.25 if bki["credit_history_months"] < 12 else 0.0
        cur = bki["current_delinquency_days"]
        x += 1.5 if cur >= 30 else 0.6 if cur >= 1 else 0.0
    arrears = float(sources["FNS"]["tax_arrears_amount"])
    x += 1.2 if arrears >= 100_000 else 0.5 if arrears > 0 else 0.0
    flags = set(sources["FNS"]["unreliable_flags"])
    x += 0.6 if flags & {"MASS_ADDRESS", "MASS_DIRECTOR"} else 0.0
    x += 1.0 if flags & {"UNRELIABLE_ADDRESS", "UNRELIABLE_DIRECTOR", "DISQUALIFIED_DIRECTOR"} else 0.0
    if req["applicant_type"] == "LEGAL_ENTITY":
        x += -2.0 * max(-0.2, min(lat["margin"], 0.3))
    x += -0.15 * math.log(lat["monthly_revenue"] / 3e6)
    # burden of the requested loan: annuity at the product base rate / true monthly revenue
    i = BASE_RATES[req["product_code"]] / 1200
    n = req["term_months"]
    pay = float(req["amount"]) * i / (1 - (1 + i) ** (-n))
    x += 3.0 * min(pay / lat["monthly_revenue"], 0.6)
    return x + noise


def generate_population(policy: dict, feature_params: dict) -> tuple[pd.DataFrame, list[dict]]:
    """Return (frame with features, flags and default; list of oracle cases)."""
    from .oracle.policy import decide

    np_rng = np.random.default_rng(SEED)
    rows, cases = [], []
    i = 0
    for cohort in COHORTS:
        for _ in range(cohort["n"]):
            i += 1
            is_ip = np_rng.random() < 0.55
            inn = synthetic_inn(i, is_ip)
            as_of = cohort["start"] + timedelta(days=int(np_rng.integers(0, cohort["days"])))
            gen = generate_borrower(Rng(seed_for(inn, "population")), inn, as_of, cohort["drift"])
            req = generate_request(Rng(seed_for(inn, "request")), gen["sources"], gen["latent"],
                                   gen["sources"]["REGISTRY"]["applicant_type"])
            case = {
                "case_id": f"POP-{i:05d}",
                "as_of_date": as_of.isoformat(),
                "application": {**req, "applicant_inn": inn},
                "state": {"auto_info_request_count": 0, "manual_review_required": False, "bank_statement_attached": False},
                "sources": gen["sources"],
            }
            feats = compute_features(case, feature_params)
            pol1 = decide(case, {"grade": "A", "score": 0, "scorecard_version": "n/a"}, policy)
            stop = pol1["outcome"] == "DECLINED" and any(c.startswith("SF_") for c in pol1["reason_codes"])
            logit = hidden_logit(feats, gen["latent"], gen["sources"], req, 0.08 * cohort["drift"], float(np_rng.normal(0, 0.5)))
            pd_true = 1 / (1 + math.exp(-logit))
            default = int(np_rng.random() < pd_true)
            row = {"case_id": case["case_id"], "inn": inn, "cohort": cohort["name"], "as_of_date": as_of,
                   "stop_factor": stop, "stop_codes": ",".join(pol1["reason_codes"]) if stop else "",
                   "default": default, "pd_true": pd_true, "product_code": req["product_code"]}
            for k in NUMERIC_FEATURES:
                v = feats.get(k)
                row[k] = float(v) if v is not None else np.nan
            for k in CATEGORICAL_FEATURES:
                row[k] = feats.get(k)
            row["current_delinquency_days"] = (gen["sources"]["CREDIT_BUREAU"] or {}).get("current_delinquency_days", 0)
            row["tax_arrears_amount"] = float(gen["sources"]["FNS"]["tax_arrears_amount"])
            rows.append(row)
            cases.append(case)
    return pd.DataFrame(rows), cases
