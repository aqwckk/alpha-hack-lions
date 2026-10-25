"""Scorecard development: binning, WoE/IV, feature selection, logistic
regression, PDO scaling, grades, validation (Gini, KS, PSI, calibration)."""

from __future__ import annotations

import math
from decimal import Decimal

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, roc_auc_score, roc_curve
from sklearn.model_selection import train_test_split

from .config_base import AS_OF, AUTHOR, FACTOR_META, FEATURE_DEFINITIONS, FEATURE_PARAMETERS, SCORECARD_VERSION

SPLIT_SEED = 7
MIN_BIN_SHARE = 0.05
MIN_MISSING_COUNT = 50
IV_MIN = 0.02
CORR_MAX = 0.6
COEF_MIN = 0.15
EXCLUDED_BY_DESIGN = {
    "requested_amount_to_revenue": "параметр заявки: по decision-model.md (раздел 7) сумма и срок учитываются политикой, а не скорингом",
    "fns_mass_registration": "MASS_ADDRESS и MASS_DIRECTOR входят в unreliable_flags политики (стоп-фактор POL-01), в обучающей выборке без стоп-факторов признак не варьируется",
}
BASE_SCORE = 600
BASE_ODDS = 50
PDO = 20
GRADE_PD_CUTS = [("A", 0.02), ("B", 0.04), ("C", 0.08), ("D", 0.15)]


# Binning
def _woe_table(bin_idx: pd.Series, y: pd.Series) -> pd.DataFrame:
    t = pd.DataFrame({"b": bin_idx, "y": y}).groupby("b")["y"].agg(["count", "sum"])
    t.columns = ["n", "bad"]
    t["good"] = t["n"] - t["bad"]
    return t


def _woe(good, bad, G, B):
    return math.log(((good + 0.5) / G) / ((bad + 0.5) / B))


def build_numeric_bins(x: pd.Series, y: pd.Series, edges: list, direction: str | None) -> list[dict]:
    """Start from candidate edges, merge sparse bins, then enforce monotonic WoE."""
    edges = [Decimal(str(e)) for e in edges]
    intervals = [[None, edges[0]]] + [[edges[i], edges[i + 1]] for i in range(len(edges) - 1)] + [[edges[-1], None]]
    mask = x.notna()
    xv = x[mask].astype(float)
    yv = y[mask]
    n_total = len(xv)

    def stats(ints):
        out = []
        for lo, hi in ints:
            m = np.ones(len(xv), dtype=bool)
            if lo is not None:
                m &= xv.values >= float(lo)
            if hi is not None:
                m &= xv.values < float(hi)
            out.append((int(m.sum()), int(yv.values[m].sum())))
        return out

    def merge(ints, i):  # merge interval i with i+1
        return ints[:i] + [[ints[i][0], ints[i + 1][1]]] + ints[i + 2:]

    changed = True
    while changed and len(intervals) > 1:
        changed = False
        st = stats(intervals)
        for i, (n, _) in enumerate(st):
            if n < MIN_BIN_SHARE * n_total:
                j = i if i < len(intervals) - 1 else i - 1
                if i > 0 and i < len(intervals) - 1:
                    # merge with the neighbour whose bad rate is closer
                    br = lambda k: st[k][1] / st[k][0] if st[k][0] else 0
                    me = br(i)
                    j = i - 1 if abs(br(i - 1) - me) <= abs(br(i + 1) - me) else i
                intervals = merge(intervals, j)
                changed = True
                break
    if direction:
        changed = True
        while changed and len(intervals) > 1:
            changed = False
            st = stats(intervals)
            rates = [b / n if n else 0 for n, b in st]
            for i in range(len(rates) - 1):
                worse_next = rates[i + 1] > rates[i]
                if (direction == "up" and worse_next) or (direction == "down" and not worse_next):
                    intervals = merge(intervals, i)
                    changed = True
                    break
    return [{"lower": lo, "upper": hi} for lo, hi in intervals]


def assign_numeric(x: pd.Series, bins: list[dict]) -> pd.Series:
    out = pd.Series(-1, index=x.index)
    for i, b in enumerate(bins):
        m = x.notna()
        if b["lower"] is not None:
            m &= x >= float(b["lower"])
        if b["upper"] is not None:
            m &= x < float(b["upper"])
        out[m] = i
    return out


def assign_categorical(x: pd.Series, bins: list[dict]) -> pd.Series:
    out = pd.Series(-1, index=x.index)
    for i, b in enumerate(bins):
        out[x.isin(b["values"])] = i
    return out


def fit_factor(code: str, x: pd.Series, y: pd.Series) -> dict:
    name, sources, ftype, spec, direction = FACTOR_META[code]
    if ftype == "numeric":
        bins = build_numeric_bins(x, y, spec, direction)
        idx = assign_numeric(x, bins)
    else:
        bins = [{"values": [v]} for v in spec if (x == v).any()]
        idx = assign_categorical(x, bins)
    G, B = int((y == 0).sum()), int((y == 1).sum())
    t = _woe_table(idx, y)
    iv = 0.0
    for i, b in enumerate(bins):
        n, bad = (int(t.loc[i, "n"]), int(t.loc[i, "bad"])) if i in t.index else (0, 0)
        good = n - bad
        b["n"], b["bad"] = n, bad
        b["woe"] = _woe(good, bad, G, B)
        iv += ((good + 0.5) / G - (bad + 0.5) / B) * b["woe"]
    n_miss = int((idx == -1).sum())
    bad_miss = int(y[idx == -1].sum())
    if n_miss >= MIN_MISSING_COUNT:
        miss_woe = _woe(n_miss - bad_miss, bad_miss, G, B)
        iv += ((n_miss - bad_miss + 0.5) / G - (bad_miss + 0.5) / B) * miss_woe
    else:
        miss_woe = 0.0
    monotonic = True
    if ftype == "numeric" and len(bins) > 1:
        w = [b["woe"] for b in bins]
        diffs = np.diff(w)
        monotonic = bool((diffs >= 0).all() or (diffs <= 0).all())
    return {
        "code": code, "name": name, "sources": sources, "type": ftype, "direction": direction,
        "bins": bins, "missing": {"n": n_miss, "bad": bad_miss, "woe": miss_woe},
        "iv": iv, "monotonic": monotonic,
    }


def woe_transform(df: pd.DataFrame, fac: dict) -> pd.Series:
    x = df[fac["code"]]
    idx = assign_numeric(x, fac["bins"]) if fac["type"] == "numeric" else assign_categorical(x, fac["bins"])
    w = pd.Series(fac["missing"]["woe"], index=df.index, dtype=float)
    for i, b in enumerate(fac["bins"]):
        w[idx == i] = b["woe"]
    return w


# Metrics
def gini_ks(y, score) -> tuple[float, float, float]:
    risk = -np.asarray(score)
    auc = roc_auc_score(y, risk)
    # ROC thresholds include tied scores together; row order cannot affect KS.
    fpr, tpr, _ = roc_curve(y, risk, drop_intermediate=False)
    ks = float(np.abs(tpr - fpr).max())
    return float(auc), float(2 * auc - 1), ks


def psi(expected: pd.Series, actual: pd.Series) -> float:
    cats = sorted(set(expected.unique()) | set(actual.unique()), key=str)
    e = expected.value_counts(normalize=True)
    a = actual.value_counts(normalize=True)
    total = 0.0
    for c in cats:
        pe = max(float(e.get(c, 0)), 1e-4)
        pa = max(float(a.get(c, 0)), 1e-4)
        total += (pa - pe) * math.log(pa / pe)
    return total


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return (c - h, c + h)


# Pipeline
def develop(pop: pd.DataFrame) -> dict:
    data = pop[~pop["stop_factor"]].copy()
    dev = data[data["cohort"] == "2024H2"].copy()
    oot = data[data["cohort"] == "2025H1"].copy()
    train, test = train_test_split(dev, test_size=0.3, random_state=SPLIT_SEED, stratify=dev["default"])
    train, test = train.copy(), test.copy()
    y = train["default"]

    candidates = {code: fit_factor(code, train[code], y) for code in FACTOR_META}
    selection = []
    for code, fac in sorted(candidates.items(), key=lambda kv: -kv[1]["iv"]):
        reason = None
        if code in EXCLUDED_BY_DESIGN:
            reason = EXCLUDED_BY_DESIGN[code]
        elif fac["iv"] < IV_MIN:
            reason = f"IV {fac['iv']:.3f} меньше порога {IV_MIN}"
        elif not fac["monotonic"]:
            reason = "немонотонный WoE"
        selection.append({"code": code, "iv": fac["iv"], "selected": reason is None, "reason": reason})

    woe_train = pd.DataFrame({c: woe_transform(train, candidates[c]) for c in candidates})
    chosen = [s["code"] for s in selection if s["selected"]]
    # correlation filter: keep the higher-IV feature of a correlated pair
    corr = woe_train[chosen].corr().abs()
    kept: list[str] = []
    for c in chosen:
        clash = [k for k in kept if corr.loc[c, k] > CORR_MAX]
        if clash:
            for s in selection:
                if s["code"] == c:
                    s["selected"] = False
                    s["reason"] = f"корреляция WoE с {clash[0]} {corr.loc[c, clash[0]]:.2f} больше {CORR_MAX}"
        else:
            kept.append(c)
    # logistic regression; drop features with a wrong (positive) sign
    while True:
        lr = LogisticRegression(C=100.0, solver="lbfgs", max_iter=5000)
        lr.fit(woe_train[kept], y)
        coefs = dict(zip(kept, lr.coef_[0]))
        wrong = [c for c, b in coefs.items() if b >= 0]
        weak = [c for c, b in coefs.items() if -COEF_MIN < b < 0]
        if not wrong and not weak:
            break
        if wrong:
            worst = max(wrong, key=lambda c: coefs[c])
            why = "неверный знак коэффициента в многофакторной модели"
        else:
            worst = max(weak, key=lambda c: coefs[c])
            why = f"незначимый вклад в многофакторной модели (коэффициент {coefs[worst]:.3f})"
        kept.remove(worst)
        for s in selection:
            if s["code"] == worst:
                s["selected"] = False
                s["reason"] = why
    alpha = float(lr.intercept_[0])

    factor = PDO / math.log(2)
    offset = BASE_SCORE - factor * math.log(BASE_ODDS)
    base_points = int(round(offset - factor * alpha))

    factors_json = []
    for c in kept:
        fac = candidates[c]
        beta = coefs[c]
        bins_json = []
        for i, b in enumerate(fac["bins"]):
            pts = int(round(-factor * beta * b["woe"]))
            if fac["type"] == "numeric":
                lo, hi = b["lower"], b["upper"]
                label = _label(lo, hi, c)
                bins_json.append({"id": f"{c.upper()}_{i + 1}", "lower": _dec(lo), "upper": _dec(hi), "label": label, "points": pts,
                                  "woe": round(b["woe"], 4), "train_count": b["n"], "train_bad_rate": round(b["bad"] / b["n"], 4) if b["n"] else None})
            else:
                bins_json.append({"id": f"{c.upper()}_{b['values'][0]}", "values": b["values"], "label": CATEGORY_LABELS.get(b["values"][0], b["values"][0]),
                                  "points": pts, "woe": round(b["woe"], 4), "train_count": b["n"],
                                  "train_bad_rate": round(b["bad"] / b["n"], 4) if b["n"] else None})
        miss = fac["missing"]
        factors_json.append({
            "code": c, "name": fac["name"], "sources": fac["sources"], "type": fac["type"],
            "definition": FEATURE_DEFINITIONS[c],
            "coefficient": round(beta, 6), "iv": round(fac["iv"], 4),
            "bins": bins_json,
            "missing": {"id": f"{c.upper()}_MISSING", "label": "нет данных", "points": min(0, int(round(-factor * beta * miss["woe"]))),
                        "points_before_cap": int(round(-factor * beta * miss["woe"])),
                        "woe": round(miss["woe"], 4), "train_count": miss["n"],
                        "train_bad_rate": round(miss["bad"] / miss["n"], 4) if miss["n"] else None},
        })

    bands = []
    for g, p in GRADE_PD_CUTS:
        s = offset + factor * math.log((1 - p) / p)
        bands.append({"grade": g, "min_score": int(5 * round(s / 5)), "pd_upper_target": p})
    bands.append({"grade": "E", "min_score": None, "pd_upper_target": None})

    scorecard = {
        "schema": "scorecard",
        "schema_version": 1,
        "version": SCORECARD_VERSION,
        "created_at": AS_OF,
        "author": AUTHOR,
        "description": "Балльная карта МСП, обучена на синтетической выборке. Балл = base_points + сумма баллов бинов всех факторов. Чем выше балл, тем ниже риск.",
        "scaling": {"base_score": BASE_SCORE, "base_odds_good_to_bad": BASE_ODDS, "pdo": PDO,
                    "factor": round(factor, 6), "offset": round(offset, 6), "intercept": round(alpha, 6)},
        "bin_rule": "числовой бин: lower <= x < upper, null означает отсутствие границы; категориальный бин: x входит в values; значение null или не попавшее ни в один бин категориального фактора: бин missing",
        "feature_parameters": FEATURE_PARAMETERS,
        "base_points": base_points,
        "factors": [{k: v for k, v in f.items()} for f in factors_json],
        "grade_bands": [{"grade": b["grade"], "min_score": b["min_score"]} for b in bands],
        "pd_by_grade": {},
    }

    from .oracle.scoring import grade_for_score

    def score_frame(frame):
        s = pd.Series(base_points, index=frame.index, dtype=int)
        for f in factors_json:
            x = frame[f["code"]]
            if f["type"] == "numeric":
                bins = [{"lower": b["lower"], "upper": b["upper"]} for b in f["bins"]]
                idx = assign_numeric(x, bins)
            else:
                idx = assign_categorical(x, f["bins"])
            pts = pd.Series(f["missing"]["points"], index=frame.index)
            for i, b in enumerate(f["bins"]):
                pts[idx == i] = b["points"]
            s += pts.astype(int)
        return s

    for frame in (train, test, oot, data):
        frame["score"] = score_frame(frame)
        frame["grade"] = frame["score"].apply(lambda v: grade_for_score(scorecard, int(v)))
        frame["pd_model"] = 1 / (1 + np.exp((frame["score"] - offset) / factor))

    # pd_by_grade from the holdout (test) sample, monotonic by construction check
    grade_rows = []
    for g in ["A", "B", "C", "D", "E"]:
        row = {"grade": g}
        for name, frame in (("train", train), ("test", test), ("oot", oot)):
            sub = frame[frame["grade"] == g]
            n, k = len(sub), int(sub["default"].sum())
            lo, hi = wilson(k, n)
            row[name] = {"n": n, "share": n / len(frame), "bad": k, "dr": k / n if n else None,
                         "pd_model_mean": float(sub["pd_model"].mean()) if n else None, "ci95": [lo, hi]}
        grade_rows.append(row)
    pd_by_grade = {}
    prev = 0.0
    for r in grade_rows:
        # pooled holdout: test (same period) and out-of-time cohort
        n_h = r["test"]["n"] + r["oot"]["n"]
        k_h = r["test"]["bad"] + r["oot"]["bad"]
        r["holdout"] = {"n": n_h, "bad": k_h, "dr": k_h / n_h if n_h else None, "ci95": list(wilson(k_h, n_h))}
        dr = r["holdout"]["dr"] or 0.0
        dr = max(dr, prev + 0.001)
        pd_by_grade[r["grade"]] = f"{dr:.4f}"
        prev = dr
    scorecard["pd_by_grade"] = pd_by_grade
    dev_n = len(train) + len(test)
    scorecard["monitoring"] = {
        "description": "Эталонное распределение грейдов выборки разработки (2024H2) для расчета PSI на экране метрик",
        "grade_distribution_dev": {r["grade"]: f"{(r['train']['n'] + r['test']['n']) / dev_n:.4f}" for r in grade_rows},
        "psi_thresholds": {"stable_below": "0.10", "review_above": "0.25"},
    }

    metrics = {}
    for name, frame in (("train", train), ("test", test), ("oot", oot)):
        auc, gini, ks = gini_ks(frame["default"], frame["score"])
        metrics[name] = {"n": len(frame), "bad": int(frame["default"].sum()), "dr": float(frame["default"].mean()),
                         "auc": auc, "gini": gini, "ks": ks,
                         "brier": float(brier_score_loss(frame["default"], frame["pd_model"]))}
    dev_all = pd.concat([train, test])
    deciles = np.unique(np.quantile(dev_all["score"], np.linspace(0, 1, 11)[1:-1]))
    cut = lambda s: np.searchsorted(deciles, s, side="right")
    psi_score = psi(pd.Series(cut(dev_all["score"])), pd.Series(cut(oot["score"])))
    psi_grade = psi(dev_all["grade"], oot["grade"])
    psi_factors = {}
    for f in factors_json:
        fac = candidates[f["code"]]
        tr = lambda fr: (assign_numeric(fr[f["code"]], fac["bins"]) if fac["type"] == "numeric" else assign_categorical(fr[f["code"]], fac["bins"]))
        psi_factors[f["code"]] = psi(tr(dev_all), tr(oot))

    # stop factor justification: default rate by segment of the whole population
    sf = {}
    allp = pop.copy()
    for label, m in [
        ("current_delinquency_0", allp["current_delinquency_days"] == 0),
        ("current_delinquency_1_29", allp["current_delinquency_days"].between(1, 29)),
        ("tax_arrears_0", allp["tax_arrears_amount"] == 0),
        ("tax_arrears_lt_100k", (allp["tax_arrears_amount"] > 0) & (allp["tax_arrears_amount"] < 100000)),
        ("tax_arrears_ge_100k", allp["tax_arrears_amount"] >= 100000),
    ]:
        sub = allp[m]
        sf[label] = {"n": len(sub), "dr": float(sub["default"].mean()) if len(sub) else None}
    for code in ["SF_CURRENT_DELINQUENCY", "SF_TAX_ARREARS", "SF_UNRELIABLE_REGISTRY_DATA", "SF_COMPANY_STATUS", "SF_BUSINESS_AGE"]:
        sub = allp[allp["stop_codes"].str.contains(code)]
        sf[code] = {"n": len(sub), "dr": float(sub["default"].mean()) if len(sub) else None}

    report = {
        "samples": {"population": len(pop), "stop_factor_excluded": int(pop["stop_factor"].sum()),
                    "train": len(train), "test": len(test), "oot": len(oot)},
        "selection": selection,
        "candidates": {c: {"iv": f["iv"], "monotonic": f["monotonic"], "bins": len(f["bins"]),
                           "missing_share": f["missing"]["n"] / len(train)} for c, f in candidates.items()},
        "coefficients": {c: coefs[c] for c in kept},
        "intercept": alpha,
        "metrics": metrics,
        "psi": {"score_deciles": psi_score, "grade": psi_grade, "factors": psi_factors},
        "grades": grade_rows,
        "stop_factor_dr": sf,
        "score_quantiles": {name: [float(v) for v in np.quantile(fr["score"], [0.05, 0.25, 0.5, 0.75, 0.95])]
                            for name, fr in (("dev", dev_all), ("oot", oot))},
    }
    frames = {"train": train, "test": test, "oot": oot, "data": data}
    return {"scorecard": scorecard, "report": report, "frames": frames}


CATEGORY_LABELS = {
    "LOW": "низкий риск отрасли", "MEDIUM": "средний риск отрасли", "HIGH": "высокий риск отрасли",
    "NO": "нет", "YES": "есть",
    "LEGAL_ENTITY": "ООО", "INDIVIDUAL_ENTREPRENEUR": "ИП",
}


def _dec(v):
    return None if v is None else str(v)


def _fmt_num(v: Decimal, code: str) -> str:
    if code in ("confirmed_monthly_revenue",):
        return f"{int(v):,}".replace(",", " ")
    if code in ("revenue_growth", "debt_load_ratio", "turnover_volatility", "net_margin", "requested_amount_to_revenue"):
        return f"{float(v) * 100:g}%"
    return f"{v}"


def _label(lo, hi, code) -> str:
    if lo is None and hi is None:
        return "любое значение"
    if lo is None:
        return f"меньше {_fmt_num(hi, code)}"
    if hi is None:
        return f"{_fmt_num(lo, code)} и больше"
    return f"от {_fmt_num(lo, code)} до {_fmt_num(hi, code)}"
