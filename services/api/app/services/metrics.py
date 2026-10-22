"""Risk manager metrics (docs/analytics/metrics.md) computed only from the event journal.

SQL selects the cohort (applications with APPLICATION_CREATED in the period, optionally by product)
and their events; the aggregation follows analytics/src/metrics.py formula by formula.
"""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime, timedelta
from decimal import Decimal
from statistics import median
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from ..domain.configs import get_registry

FINAL = {"APPROVED", "COUNTER_OFFER", "DECLINED"}
LGD = {"INVESTMENT": Decimal("0.4")}
LGD_DEFAULT = Decimal("0.6")


def _median(values: list) -> float | None:
    return median(values) if values else None


def _share(n: int, d: int) -> float | None:
    return round(n / d, 4) if d else None


def load_events(session: Session, start: datetime, end: datetime, product_code: str | None) -> tuple[dict[str, list[dict]], set[str]]:
    params: dict[str, Any] = {"start": start, "end": end, "product": product_code}
    rows = session.execute(
        text(
            """
            WITH cohort AS (
                SELECT application_id FROM events
                WHERE event_type = 'APPLICATION_CREATED' AND occurred_at >= :start AND occurred_at < :end
                  AND (CAST(:product AS text) IS NULL OR payload->>'product_code' = :product)
            )
            SELECT e.application_id::text AS app, e.event_type, e.occurred_at, e.payload
            FROM events e JOIN cohort c ON c.application_id = e.application_id
            ORDER BY e.occurred_at, e.seq
            """
        ),
        params,
    ).mappings()
    by_app: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_app[r["app"]].append({"event_type": r["event_type"], "occurred_at": r["occurred_at"], "payload": r["payload"] or {}})
    wizard = set(
        session.execute(
            text(
                "SELECT DISTINCT payload->>'wizard_session_id' FROM events WHERE event_type = 'PRODUCT_WIZARD_STARTED' AND occurred_at >= :start AND occurred_at < :end"
            ),
            {"start": start, "end": end},
        ).scalars()
    )
    return by_app, wizard


def compute(session: Session, start: datetime, end: datetime, product_code: str | None = None) -> dict[str, Any]:
    pol = get_registry().policy_content()
    sc = get_registry().require()[0].content
    sla_auto = pol["process"]["decision_sla_auto_minutes"] * 60
    sla_manual = pol["process"]["decision_sla_manual_hours"] * 3600
    by_app, wizard_started = load_events(session, start, end, product_code)

    def has(evs, t):
        return any(e["event_type"] == t for e in evs)

    cohort = list(by_app)
    wizard_to_app = {next(e for e in by_app[a] if e["event_type"] == "APPLICATION_CREATED")["payload"].get("wizard_session_id") for a in cohort}
    created = len(cohort)
    submitted = [a for a in cohort if has(by_app[a], "APPLICATION_SUBMITTED")]
    fill = [next(e for e in by_app[a] if e["event_type"] == "APPLICATION_SUBMITTED")["payload"].get("fill_duration_sec") for a in submitted]
    fill = [f for f in fill if f is not None]
    prefill = [e["payload"] for a in cohort for e in by_app[a] if e["event_type"] == "PREFILL_COMPLETED"]
    first_final: dict[str, dict] = {}
    for a in cohort:
        for e in by_app[a]:
            if e["event_type"] == "DECISION_MADE" and e["payload"].get("outcome") in FINAL:
                first_final[a] = e
                break
    finals = list(first_final.values())
    in_sla = sum(1 for e in finals if (e["payload"].get("time_from_submit_sec") or 0) <= (sla_auto if e["payload"].get("mode") == "AUTO" else sla_manual))
    manual_finals = [(a, e) for a, e in first_final.items() if e["payload"].get("mode") == "MANUAL"]
    manual_ok = sum(1 for a, _ in manual_finals if not has(by_app[a], "REVIEW_SLA_BREACHED"))
    info_apps = [a for a in submitted if has(by_app[a], "INFO_REQUESTED")]
    info_cycles = [sum(1 for e in by_app[a] if e["event_type"] == "INFO_REQUESTED") for a in info_apps]
    issued = {"APPROVED": 0, "COUNTER_OFFER": 0}
    accepted = {"APPROVED": 0, "COUNTER_OFFER": 0}
    line_chosen = 0
    for a in cohort:
        last_outcome = None
        offer_outcome: dict[str, str] = {}
        for e in by_app[a]:
            p = e["payload"]
            if e["event_type"] == "DECISION_MADE":
                last_outcome = p.get("outcome")
            elif e["event_type"] == "OFFER_ISSUED" and last_outcome in issued:
                issued[last_outcome] += 1
                offer_outcome[p.get("offer_id")] = last_outcome
            elif e["event_type"] == "OFFER_ACCEPTED" and p.get("offer_id") in offer_outcome:
                accepted[offer_outcome[p["offer_id"]]] += 1
                line_chosen += p.get("product_code") == "CREDIT_LINE"
    manual_all = [e for a in cohort for e in by_app[a] if e["event_type"] == "DECISION_MADE" and e["payload"].get("mode") == "MANUAL" and e["payload"].get("outcome") in FINAL]
    attempts_ok = sum(1 for a in cohort for e in by_app[a] if e["event_type"] == "SOURCE_REQUEST_SUCCEEDED" and not e["payload"].get("from_cache"))
    attempts_fail = sum(1 for a in cohort for e in by_app[a] if e["event_type"] == "SOURCE_REQUEST_FAILED")
    fail_by_source: dict[str, int] = defaultdict(int)
    for a in cohort:
        for e in by_app[a]:
            if e["event_type"] == "SOURCE_REQUEST_FAILED":
                fail_by_source[e["payload"].get("source")] += 1
    outcomes: dict[str, int] = defaultdict(int)
    for e in finals:
        outcomes[e["payload"]["outcome"]] += 1
    stop_codes: dict[str, int] = defaultdict(int)
    for a in first_final:
        for e in by_app[a]:
            if e["event_type"] == "STOP_FACTOR_TRIGGERED":
                stop_codes[e["payload"].get("reason_code")] += 1
    issued_loans = [a for a in cohort if has(by_app[a], "LOAN_ISSUED")]
    waits = [e["payload"].get("wait_sec") for a in cohort for e in by_app[a] if e["event_type"] == "REVIEW_TAKEN" and e["payload"].get("wait_sec") is not None]

    grades: dict[str, int] = defaultdict(int)
    for a in cohort:
        last = [e for e in by_app[a] if e["event_type"] == "SCORING_COMPLETED"]
        if last:
            grades[last[-1]["payload"].get("grade")] += 1
    scored = sum(grades.values())
    dev = sc["monitoring"]["grade_distribution_dev"]
    psi = None
    if scored:
        psi = 0.0
        for g, ref in dev.items():
            actual = max(grades.get(g, 0) / scored, 1e-4)
            expected = float(ref)
            psi += (actual - expected) * math.log(actual / expected)
        psi = round(psi, 4)
    expected_loss = Decimal(0)
    for a in issued_loans:
        loan = next(e for e in by_app[a] if e["event_type"] == "LOAN_ISSUED")["payload"]
        grade = next((e["payload"].get("grade") for e in reversed(by_app[a]) if e["event_type"] == "SCORING_COMPLETED"), None)
        if grade:
            expected_loss += Decimal(sc["pd_by_grade"][grade]) * LGD.get(loan.get("product_code"), LGD_DEFAULT) * Decimal(loan.get("amount") or "0")
    funnel = {
        "wizard_started": len(wizard_started),
        "created": created,
        "submitted": len(submitted),
        "decided": len(finals),
        "offer_accepted": accepted["APPROVED"] + accepted["COUNTER_OFFER"],
        "signed": sum(1 for a in cohort if has(by_app[a], "DOCUMENTS_SIGNED")),
        "issued": len(issued_loans),
    }
    return {
        "period": {"start": start.isoformat(), "end": end.isoformat(), "product_code": product_code, "complete": end <= datetime.now(start.tzinfo)},
        "applications_created": created,
        "north_star": _share(in_sla, created),
        "time_to_decision_median_sec": median([e["payload"]["time_from_submit_sec"] for e in finals]) if finals else None,
        "time_to_decision_auto_median_sec": _median([e["payload"]["time_from_submit_sec"] for e in finals if e["payload"].get("mode") == "AUTO"]),
        "time_to_decision_manual_median_sec": _median([e["payload"]["time_from_submit_sec"] for e in finals if e["payload"].get("mode") == "MANUAL"]),
        "wizard_conversion": _share(len(wizard_to_app & wizard_started), len(wizard_started)),
        "fill_conversion": _share(len(submitted), created),
        "fill_duration_median_sec": median(fill) if fill else None,
        "prefill_share": _share(sum(p.get("fields_prefilled", 0) for p in prefill), sum(p.get("fields_total", 0) for p in prefill)),
        "completeness_first_time": _share(sum(1 for a in submitted if not has(by_app[a], "COMPLETENESS_FAILED")), len(submitted)),
        "info_request_share": _share(len(info_apps), len(submitted)),
        "info_request_cycles_avg": round(sum(info_cycles) / len(info_cycles), 3) if info_cycles else None,
        "auto_decision_share": _share(sum(1 for e in finals if e["payload"].get("mode") == "AUTO"), len(finals)),
        "manual_review_sla_share": _share(manual_ok, len(manual_finals)),
        "queue_wait_median_sec": median(waits) if waits else None,
        "outcomes": {k: _share(v, len(finals)) for k, v in sorted(outcomes.items())},
        "approval_rate": _share(outcomes["APPROVED"] + outcomes["COUNTER_OFFER"], len(finals)),
        "offer_acceptance": _share(accepted["APPROVED"] + accepted["COUNTER_OFFER"], issued["APPROVED"] + issued["COUNTER_OFFER"]),
        "counter_offer_acceptance": _share(accepted["COUNTER_OFFER"], issued["COUNTER_OFFER"]),
        "credit_line_chosen": line_chosen,
        "stop_factor_share": _share(sum(1 for a in first_final if has(by_app[a], "STOP_FACTOR_TRIGGERED")), len(finals)),
        "stop_factor_codes": dict(stop_codes),
        "override_share": _share(sum(1 for e in manual_all if e["payload"].get("override")), len(manual_all)),
        "integration_failed_attempt_share": _share(attempts_fail, attempts_ok + attempts_fail),
        "integration_failures_by_source": dict(fail_by_source),
        "enrichment_retries": sum(1 for a in cohort for e in by_app[a] if e["event_type"] == "ENRICHMENT_RETRY_SCHEDULED"),
        "processing_error_applications": sum(1 for a in cohort if has(by_app[a], "PROCESSING_FAILED")),
        "end_to_end_conversion": _share(len(issued_loans), created),
        "grade_distribution": {g: _share(grades.get(g, 0), scored) for g in dev},
        "grade_psi": psi,
        "expected_loss_issued": str(expected_loss.quantize(Decimal("0.01"))),
        "funnel": funnel,
        "targets": {
            "wizard_conversion": 0.6, "fill_conversion": 0.7, "fill_duration_median_sec": 300, "prefill_share": 0.6, "completeness_first_time": 0.9,
            "info_request_share": 0.3, "info_request_cycles_avg": 1.2, "auto_decision_share": 0.6, "manual_review_sla_share": 0.9,
            "offer_acceptance": 0.7, "counter_offer_acceptance": 0.5, "grade_psi": 0.1,
        },
    }


def period(days: int | None, start: datetime | None, end: datetime | None, now: datetime) -> tuple[datetime, datetime]:
    if start and end:
        return start, end
    return now - timedelta(days=days or 30), now
