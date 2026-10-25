"""Reference calculation of the BK-06 metrics from the event log.

Definitions are in docs/analytics/metrics.md. The function works on a list of
events in the format of docs/process/events.md and is used to check the
synthetic history; the backend implements the same formulas in SQL.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from statistics import median

FINAL = {"APPROVED", "COUNTER_OFFER", "DECLINED"}


def _ts(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def compute_metrics(events: list[dict], period_start: str, period_end: str, sla_auto_sec: int = 900, sla_manual_sec: int = 86400) -> dict:
    ps, pe = _ts(period_start), _ts(period_end)
    by_app: dict[str, list[dict]] = defaultdict(list)
    wizard_started, wizard_to_app = set(), set()
    for e in sorted(events, key=lambda e: e["occurred_at"]):
        t = _ts(e["occurred_at"])
        if e["event_type"] == "PRODUCT_WIZARD_STARTED" and ps <= t < pe:
            wizard_started.add(e["payload"]["wizard_session_id"])
        if e["application_id"]:
            by_app[e["application_id"]].append(e)

    cohort = []  # applications created in the period
    for app_id, evs in by_app.items():
        created = next((e for e in evs if e["event_type"] == "APPLICATION_CREATED"), None)
        if created and ps <= _ts(created["occurred_at"]) < pe:
            cohort.append(app_id)
            wizard_to_app.add(created["payload"].get("wizard_session_id"))

    def has(evs, etype):
        return any(e["event_type"] == etype for e in evs)

    created_n = len(cohort)
    submitted = [a for a in cohort if has(by_app[a], "APPLICATION_SUBMITTED")]
    fill = [next(e for e in by_app[a] if e["event_type"] == "APPLICATION_SUBMITTED")["payload"]["fill_duration_sec"] for a in submitted]
    prefill = [e["payload"] for a in cohort for e in by_app[a] if e["event_type"] == "PREFILL_COMPLETED"]
    first_final = {}
    for a in cohort:
        for e in by_app[a]:
            if e["event_type"] == "DECISION_MADE" and e["payload"]["outcome"] in FINAL:
                first_final[a] = e
                break
    in_sla = 0
    for a, e in first_final.items():
        lim = sla_auto_sec if e["payload"]["mode"] == "AUTO" else sla_manual_sec
        if e["payload"]["time_from_submit_sec"] <= lim:
            in_sla += 1
    finals = list(first_final.values())
    auto_times = [e["payload"]["time_from_submit_sec"] for e in finals if e["payload"]["mode"] == "AUTO"]
    manual_finals = [(a, e) for a, e in first_final.items() if e["payload"]["mode"] == "MANUAL"]
    manual_ok = sum(1 for a, e in manual_finals if not has(by_app[a], "REVIEW_SLA_BREACHED"))
    info_apps = [a for a in submitted if has(by_app[a], "INFO_REQUESTED")]
    info_cycles = [sum(1 for e in by_app[a] if e["event_type"] == "INFO_REQUESTED") for a in info_apps]
    # offers and their decision outcome
    issued = {"APPROVED": 0, "COUNTER_OFFER": 0}
    accepted = {"APPROVED": 0, "COUNTER_OFFER": 0}
    line_chosen = 0
    for a in cohort:
        last_outcome = None
        offer_outcome = {}
        for e in by_app[a]:
            if e["event_type"] == "DECISION_MADE":
                last_outcome = e["payload"]["outcome"]
            elif e["event_type"] == "OFFER_ISSUED" and last_outcome in issued:
                issued[last_outcome] += 1
                offer_outcome[e["payload"]["offer_id"]] = last_outcome
            elif e["event_type"] == "OFFER_ACCEPTED" and e["payload"]["offer_id"] in offer_outcome:
                accepted[offer_outcome[e["payload"]["offer_id"]]] += 1
                line_chosen += e["payload"]["product_code"] == "CREDIT_LINE"
    manual_all = [e for a in cohort for e in by_app[a] if e["event_type"] == "DECISION_MADE" and e["payload"]["mode"] == "MANUAL"
                  and e["payload"]["outcome"] in FINAL]
    attempts_ok = sum(1 for a in cohort for e in by_app[a] if e["event_type"] == "SOURCE_REQUEST_SUCCEEDED" and not e["payload"]["from_cache"])
    attempts_fail = sum(1 for a in cohort for e in by_app[a] if e["event_type"] == "SOURCE_REQUEST_FAILED")
    outcome_counts = defaultdict(int)
    for e in finals:
        outcome_counts[e["payload"]["outcome"]] += 1
    issued_loans = [a for a in cohort if has(by_app[a], "LOAN_ISSUED")]
    current_status = {}
    for a in cohort:
        st = [e for e in by_app[a] if e["event_type"] == "STATUS_CHANGED"]
        current_status[a] = st[-1]["payload"]["to_status"] if st else None
    status_counts = defaultdict(int)
    for s in current_status.values():
        status_counts[s] += 1

    def share(n, d):
        return round(n / d, 4) if d else None

    return {
        "period": {"start": period_start, "end": period_end},
        "applications_created": created_n,
        "north_star": share(in_sla, created_n),
        "time_to_decision_median_sec": median([e["payload"]["time_from_submit_sec"] for e in finals]) if finals else None,
        "time_to_decision_auto_median_sec": median(auto_times) if auto_times else None,
        "wizard_conversion": share(len(wizard_to_app & wizard_started), len(wizard_started)),
        "fill_conversion": share(len(submitted), created_n),
        "fill_duration_median_sec": median(fill) if fill else None,
        "prefill_share": share(sum(p["fields_prefilled"] for p in prefill), sum(p["fields_total"] for p in prefill)),
        "completeness_first_time": share(sum(1 for a in submitted if not has(by_app[a], "COMPLETENESS_FAILED")), len(submitted)),
        "info_request_share": share(len(info_apps), len(submitted)),
        "info_request_cycles_avg": round(sum(info_cycles) / len(info_cycles), 3) if info_cycles else None,
        "auto_decision_share": share(sum(1 for e in finals if e["payload"]["mode"] == "AUTO"), len(finals)),
        "manual_review_sla_share": share(manual_ok, len(manual_finals)),
        "outcomes": {k: share(v, len(finals)) for k, v in sorted(outcome_counts.items())},
        "approval_rate": share(outcome_counts["APPROVED"] + outcome_counts["COUNTER_OFFER"], len(finals)),
        "offer_acceptance": share(accepted["APPROVED"] + accepted["COUNTER_OFFER"], issued["APPROVED"] + issued["COUNTER_OFFER"]),
        "counter_offer_acceptance": share(accepted["COUNTER_OFFER"], issued["COUNTER_OFFER"]),
        "credit_line_chosen": line_chosen,
        "stop_factor_share": share(sum(1 for a in first_final if has(by_app[a], "STOP_FACTOR_TRIGGERED")), len(finals)),
        "override_share": share(sum(1 for e in manual_all if e["payload"]["override"]), len(manual_all)),
        "integration_failed_attempt_share": share(attempts_fail, attempts_ok + attempts_fail),
        "enrichment_retries": sum(1 for a in cohort for e in by_app[a] if e["event_type"] == "ENRICHMENT_RETRY_SCHEDULED"),
        "processing_error_applications": sum(1 for a in cohort if has(by_app[a], "PROCESSING_FAILED")),
        "end_to_end_conversion": share(len(issued_loans), created_n),
        "status_now": dict(sorted(status_counts.items(), key=lambda kv: str(kv[0]))),
    }
