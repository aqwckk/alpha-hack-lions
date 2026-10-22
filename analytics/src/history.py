"""Synthetic application history for the risk manager metrics screen (BK-06).

Discrete-event simulation of ~420 applications created during the 90 days
before REFERENCE_NOW. Every application goes through the canonical state
machine (docs/process/application-states.md, transitions T-xx) and writes
events from the catalog (docs/process/events.md). Credit decisions are made
by the reference scoring and policy (src.oracle) on mock-generated profiles.
"""

from __future__ import annotations

import random
import uuid
from datetime import datetime, timedelta, timezone

from .mockgen import Rng, generate_borrower, generate_request, seed_for
from .oracle.inn import complete_inn
from .oracle.money import schedule_totals
from .oracle.policy import decide, rate_for
from .oracle.scoring import score_case

SEED = 4242
REFERENCE_NOW = datetime(2026, 10, 22, 21, 0, 0, tzinfo=timezone.utc)  # 2026-10-23 00:00 MSK
WINDOW_DAYS = 90
N_APPLICATIONS = 420
N_WIZARD_ONLY = 170
NS = uuid.UUID("6c1f8a52-6a59-4a8e-9d0b-3c1f0e7d2a10")
UNDERWRITERS = ["uw.dmitry", "uw.anna"]
RISK = "risk.elena"
SOURCES_LLC = ["REGISTRY", "FNS", "FINANCIAL_STATEMENTS", "CREDIT_BUREAU", "BANK_TURNOVER"]
SOURCES_IP = ["REGISTRY", "FNS", "CREDIT_BUREAU", "BANK_TURNOVER"]


class Stop(Exception):
    pass


def iso(t: datetime) -> str:
    return t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Sim:
    def __init__(self, n: int, rng: random.Random, created: datetime, client_login: str):
        self.n = n
        self.rng = rng
        self.app_id = str(uuid.uuid5(NS, f"application-{n}"))
        self.t = created
        self.events: list[dict] = []
        self.status: str | None = None
        self.version = 0
        self.seq = 0
        self.client = client_login
        self.corr = 0
        self.rec: dict = {"assignee": None, "manual_review_required": False, "sla_breached": False,
                          "auto_info_request_count": 0, "info_request_count": 0, "decisions": [], "offers": []}

    def wait(self, seconds: float):
        self.t = self.t + timedelta(seconds=max(1, int(seconds)))
        if self.t > REFERENCE_NOW:
            raise Stop()

    def ev(self, etype: str, actor: str, payload: dict, actor_login: str | None = None, app=True):
        self.seq += 1
        self.events.append({
            "event_id": str(uuid.uuid5(NS, f"event-{self.n}-{self.seq}")),
            "event_type": etype,
            "occurred_at": iso(self.t),
            "application_id": self.app_id if app else None,
            "actor_type": actor,
            "actor_login": actor_login if actor_login else (self.client if actor == "CLIENT" else None),
            "correlation_id": f"corr-{self.n:05d}-{self.corr:03d}",
            "application_version": self.version if app else None,
            "payload": payload,
        })

    def move(self, to: str, tid: str, actor: str = "SYSTEM", trigger: str = "", login: str | None = None):
        self.corr += 1
        frm = self.status
        self.status = to
        self.version += 1
        self.ev("STATUS_CHANGED", actor, {"from_status": frm, "to_status": to, "transition_id": tid, "command": trigger}, login)


def build_history(scorecard: dict, policy: dict) -> dict:
    rng = random.Random(SEED)
    start = REFERENCE_NOW - timedelta(days=WINDOW_DAYS)
    apps, events = [], []

    def arrival() -> datetime:
        while True:
            d = start + timedelta(days=rng.random() * WINDOW_DAYS)
            if d.weekday() >= 5 and rng.random() > 0.4:
                continue
            hour_msk = rng.choice([9, 10, 10, 11, 11, 12, 13, 14, 14, 15, 16, 17, 18, 19, 20, 21])
            return d.replace(hour=(hour_msk - 3) % 24, minute=rng.randint(0, 59), second=rng.randint(0, 59), microsecond=0)

    # wizard sessions that did not produce an application
    for k in range(N_WIZARD_ONLY):
        t = arrival()
        if t > REFERENCE_NOW:
            continue
        ws = str(uuid.uuid5(NS, f"wizard-only-{k}"))
        events.append({"event_id": str(uuid.uuid5(NS, f"wizard-only-ev-{k}")), "event_type": "PRODUCT_WIZARD_STARTED",
                       "occurred_at": iso(t), "application_id": None, "actor_type": "CLIENT", "actor_login": f"hist.client.{900 + k % 60:03d}",
                       "correlation_id": f"wiz-{k:04d}", "application_version": None, "payload": {"wizard_session_id": ws}})

    created_list = sorted(arrival() for _ in range(N_APPLICATIONS))
    for n, created in enumerate(created_list, start=1):
        is_ip = rng.random() < 0.55
        inn = complete_inn(f"0050{n:06d}") if is_ip else complete_inn(f"0060{n:05d}")
        gen = generate_borrower(Rng(seed_for(inn)), inn, created.date())
        src = gen["sources"]
        req = generate_request(Rng(seed_for(inn, "history-request")), src, gen["latent"], src["REGISTRY"]["applicant_type"])
        client = f"hist.client.{n:03d}"
        sim = Sim(n, rng, created - timedelta(minutes=rng.randint(1, 6)), client)
        record = {
            "id": sim.app_id, "application_number": f"A-{n:06d}",
            "client_login": client, "applicant_inn": inn, "applicant_type": src["REGISTRY"]["applicant_type"],
            "company_short_name": src["REGISTRY"]["company_short_name"],
            "product_code": req["product_code"], "purpose": req["purpose"], "amount": req["amount"], "term_months": req["term_months"],
            "monthly_revenue_declared": req["monthly_revenue_declared"],
            "existing_monthly_payments_declared": req["existing_monthly_payments_declared"],
            "collateral_value": req["collateral_value"], "collateral_type": req["collateral_type"],
            "created_at": None, "submitted_at": None, "decided_at": None, "issued_at": None, "closed_at": None,
            "score": None, "grade": None, "scorecard_version": None, "policy_version": None,
            "final_product_code": None, "final_amount": None, "final_term_months": None, "final_rate_percent": None,
            "final_monthly_payment": None, "cancel_reason": None,
        }
        sim.rec.update(record)
        try:
            simulate(sim, rng, src, req, scorecard, policy)
        except Stop:
            pass
        sim.rec["status"] = sim.status
        sim.rec["version"] = sim.version
        apps.append(sim.rec)
        events.extend(sim.events)
    events.sort(key=lambda e: (e["occurred_at"], e["event_id"]))
    return {"applications": apps, "events": events}


def simulate(sim: Sim, rng: random.Random, src: dict, req: dict, scorecard: dict, policy: dict):
    r = sim.rec
    ws = str(uuid.uuid5(NS, f"wizard-{sim.n}"))
    sim.ev("PRODUCT_WIZARD_STARTED", "CLIENT", {"wizard_session_id": ws}, app=False)
    sim.wait(rng.randint(40, 300))
    sim.ev("PRODUCT_SELECTED", "CLIENT", {"wizard_session_id": ws, "product_code": req["product_code"], "purpose": req["purpose"],
                                          "amount": req["amount"], "term_months": req["term_months"], "rank": 1 if rng.random() < 0.85 else 2,
                                          "was_recommended": rng.random() < 0.85}, app=False)
    sim.wait(rng.randint(2, 20))
    r["created_at"] = iso(sim.t)
    sim.move("DRAFT", "T-01", "CLIENT", "CREATE_APPLICATION")
    sim.ev("APPLICATION_CREATED", "CLIENT", {"product_code": req["product_code"], "purpose": req["purpose"], "amount": req["amount"],
                                              "term_months": req["term_months"], "wizard_session_id": ws})
    created_t = sim.t
    sim.wait(rng.randint(20, 120))
    reg = src["REGISTRY"]
    if rng.random() < 0.03:
        sim.ev("PREFILL_FAILED", "CLIENT", {"reason": "SOURCE_UNAVAILABLE"})
    else:
        total = 13 if r["applicant_type"] == "LEGAL_ENTITY" else 11
        sim.ev("PREFILL_COMPLETED", "CLIENT", {"applicant_type": r["applicant_type"], "fields_prefilled": total - rng.randint(0, 2),
                                                "fields_total": total, "sources": ["REGISTRY", "FNS"], "latency_ms": rng.randint(300, 2500)})
    early = []
    prod = policy["products"][req["product_code"]]
    from .oracle.features import months_between, parse_date
    if reg["company_status"] in policy["stop_factors"]["blocked_company_statuses"]:
        early.append("SF_COMPANY_STATUS")
    if months_between(parse_date(reg["registration_date"]), sim.t.date()) < prod["min_business_age_months"]:
        early.append("SF_BUSINESS_AGE")
    if set(src["FNS"]["unreliable_flags"]) & set(policy["stop_factors"]["unreliable_flags"]):
        early.append("SF_UNRELIABLE_REGISTRY_DATA")
    if early:
        sim.ev("EARLY_CHECK_WARNING_SHOWN", "CLIENT", {"product_code": req["product_code"], "reason_codes": early})
    abandon_p = 0.45 if early else 0.14
    for ctype, ver in [("CONSENT_PERSONAL_DATA", "PD-2026-10-v1"), ("CONSENT_CREDIT_BUREAU", "BKI-2026-10-v1"), ("AUTHORITY_CONFIRMATION", "AUTH-2026-10-v1")]:
        sim.wait(rng.randint(10, 60))
        sim.ev("CONSENT_GIVEN", "CLIENT", {"consent_type": ctype, "text_version": ver,
                                            "expires_at": iso(sim.t + timedelta(days=182)) if ctype == "CONSENT_CREDIT_BUREAU" else None})
    if rng.random() < abandon_p:
        if rng.random() < 0.3:
            sim.wait(rng.randint(600, 86400 * 3))
            r["cancel_reason"] = "CL_WITHDRAWN"
            sim.move("CANCELLED", "T-04", "CLIENT", "WITHDRAW")
            sim.ev("APPLICATION_CANCELLED", "CLIENT", {"cancel_reason": "CL_WITHDRAWN", "from_status": "DRAFT"})
        else:
            sim.t = created_t
            sim.wait(86400 * policy["process"]["draft_ttl_days"])
            r["cancel_reason"] = "CL_DRAFT_EXPIRED"
            sim.move("CANCELLED", "T-05", "TIMER", "DRAFT_EXPIRY")
            sim.ev("APPLICATION_CANCELLED", "TIMER", {"cancel_reason": "CL_DRAFT_EXPIRED", "from_status": "DRAFT"})
        r["closed_at"] = iso(sim.t)
        return
    sim.wait(rng.choice([rng.randint(60, 300), rng.randint(60, 300), rng.randint(300, 1500)]))
    fill = int((sim.t - created_t).total_seconds())
    r["submitted_at"] = iso(sim.t)
    submitted_t = sim.t
    sim.move("SUBMITTED", "T-03", "CLIENT", "SUBMIT")
    sim.ev("APPLICATION_SUBMITTED", "CLIENT", {"product_code": req["product_code"], "purpose": req["purpose"], "amount": req["amount"],
                                                "term_months": req["term_months"], "fill_duration_sec": fill})
    state = {"auto_info_request_count": 0, "manual_review_required": False, "bank_statement_attached": False}
    ctx = {"submitted_t": submitted_t, "cached": False, "completeness_attempt": 0, "uw_info_done": False, "final_done": False}

    # completeness: investment applications sometimes miss documents
    if req["product_code"] == "INVESTMENT" and rng.random() < 0.15:
        sim.wait(rng.randint(5, 40))
        ctx["completeness_attempt"] += 1
        sim.ev("COMPLETENESS_FAILED", "SYSTEM", {"missing_items": ["SUPPLIER_QUOTE"]})
        state["auto_info_request_count"] += 1
        r["auto_info_request_count"] += 1
        r["info_request_count"] += 1
        if not client_answers(sim, rng, "COMPLETENESS_CHECK", [{"reason_code": "NI_MISSING_DOCUMENTS", "answer_type": "DOCUMENT"}],
                              "T-07", policy, cycle=r["info_request_count"]):
            return
    pipeline(sim, rng, src, req, state, ctx, scorecard, policy)


def client_answers(sim, rng, source, items, tid, policy, cycle) -> bool:
    """INFO_REQUESTED -> client answers (T-10) or timeout (T-12). Returns True if answered."""
    r = sim.rec
    sim.move("INFO_REQUESTED", tid, "UNDERWRITER" if source == "UNDERWRITER" else "SYSTEM",
             "REQUEST_INFO" if source == "UNDERWRITER" else "COMPLETENESS_CHECK" if source == "COMPLETENESS_CHECK" else "DECIDE",
             r["assignee"] if source == "UNDERWRITER" else None)
    irid = str(uuid.uuid5(NS, f"info-{sim.n}-{cycle}"))
    due = sim.t + timedelta(days=policy["process"]["info_response_ttl_days"])
    sim.ev("INFO_REQUESTED", "UNDERWRITER" if source == "UNDERWRITER" else "SYSTEM",
           {"info_request_id": irid, "source": source, "items": items, "due_at": iso(due), "cycle_number": cycle},
           r["assignee"] if source == "UNDERWRITER" else None)
    asked = sim.t
    if rng.random() < (0.85 if source != "POLICY" else 0.75):
        sim.wait(rng.randint(1800, 86400 * 2))
        changed = ["monthly_revenue_declared"] if any(i["reason_code"] in ("NI_INCOME_NOT_CONFIRMED", "NI_DATA_MISMATCH_EXPLANATION") for i in items) else []
        sim.move("SUBMITTED", "T-10", "CLIENT", "RESPOND_INFO")
        sim.ev("INFO_PROVIDED", "CLIENT", {"info_request_id": irid, "response_duration_sec": int((sim.t - asked).total_seconds()),
                                            "changed_fields": changed})
        sim.wait(rng.randint(3, 30))
        return True
    sim.t = due
    if sim.t > REFERENCE_NOW:
        raise Stop()
    r["cancel_reason"] = "CL_INFO_TIMEOUT"
    sim.move("CANCELLED", "T-12", "TIMER", "INFO_REQUEST_EXPIRY")
    sim.ev("APPLICATION_CANCELLED", "TIMER", {"cancel_reason": "CL_INFO_TIMEOUT", "from_status": "INFO_REQUESTED"})
    r["closed_at"] = iso(sim.t)
    return False


def pipeline(sim, rng, src, req, state, ctx, scorecard, policy):
    r = sim.rec
    sim.wait(rng.randint(2, 20))
    ctx["completeness_attempt"] += 1
    sim.move("ENRICHMENT", "T-06", "SYSTEM", "COMPLETENESS_CHECK")
    sim.ev("COMPLETENESS_PASSED", "SYSTEM", {"attempt": ctx["completeness_attempt"]})
    sources = SOURCES_LLC if r["applicant_type"] == "LEGAL_ENTITY" else SOURCES_IP
    retries = 0
    t0 = sim.t
    failing = None if ctx["cached"] else ("CREDIT_BUREAU" if rng.random() < 0.06 else None)
    for s in sources:
        if s == failing:
            continue
        sim.ev("SOURCE_REQUEST_SUCCEEDED", "SYSTEM", {"source": s, "attempt": 1, "latency_ms": rng.randint(5, 40) if ctx["cached"] else rng.randint(150, 2200),
                                                     "from_cache": ctx["cached"]})
    if failing:
        for a in (1, 2, 3):
            sim.wait(5 + 2 ** (a - 1))
            sim.ev("SOURCE_REQUEST_FAILED", "SYSTEM", {"source": failing, "attempt": a, "error_code": "SOURCE_TIMEOUT", "latency_ms": 5000})
        schedule = [30, 60, 120, 300, 600]
        n_fail = 1 if rng.random() < 0.7 else (2 if rng.random() < 0.8 else 6)
        attempt = 3
        for k in range(min(n_fail, 5)):
            retries += 1
            nxt = sim.t + timedelta(seconds=schedule[k])
            sim.move("EXTERNAL_SERVICE_UNAVAILABLE", "T-14", "SYSTEM", "ENRICH")
            sim.ev("ENRICHMENT_RETRY_SCHEDULED", "SYSTEM", {"failed_sources": [failing], "retry_number": k + 1, "next_retry_at": iso(nxt)})
            sim.wait(schedule[k])
            sim.move("ENRICHMENT", "T-15", "TIMER", "ENRICHMENT_RETRY")
            attempt += 1
            if k + 1 < n_fail:
                sim.wait(5)
                sim.ev("SOURCE_REQUEST_FAILED", "SYSTEM", {"source": failing, "attempt": attempt, "error_code": "SOURCE_TIMEOUT", "latency_ms": 5000})
        if n_fail > 5:
            sim.ev("ENRICHMENT_FAILED", "SYSTEM", {"failed_sources": [failing], "retries_total": retries, "last_error_code": "SOURCE_TIMEOUT"})
            sim.move("PROCESSING_ERROR", "T-16", "SYSTEM", "ENRICH")
            sim.ev("PROCESSING_FAILED", "SYSTEM", {"failed_stage": "ENRICHMENT", "last_error_code": "SOURCE_TIMEOUT"})
            sim.wait(rng.randint(1800, 4 * 3600))
            uw = rng.choice(UNDERWRITERS)
            sim.move("ENRICHMENT", "T-44", "UNDERWRITER", "RETRY_PROCESSING", uw)
            sim.ev("PROCESSING_RETRIED", "UNDERWRITER", {"failed_stage": "ENRICHMENT"}, uw)
            attempt = 1
        sim.wait(rng.randint(1, 3))
        sim.ev("SOURCE_REQUEST_SUCCEEDED", "SYSTEM", {"source": failing, "attempt": attempt, "latency_ms": rng.randint(300, 2500), "from_cache": False})
    sim.wait(rng.randint(1, 4))
    ctx["cached"] = True
    sim.move("SCORING", "T-13", "SYSTEM", "ENRICH")
    sim.ev("ENRICHMENT_COMPLETED", "SYSTEM", {"sources": sources, "duration_ms": int((sim.t - t0).total_seconds() * 1000) + rng.randint(200, 900),
                                               "retries_total": retries})
    as_of = sim.t.date().isoformat()
    case = {"case_id": r["application_number"], "as_of_date": as_of, "application": {**req, "applicant_inn": r["applicant_inn"]},
            "state": dict(state), "sources": src}
    sc = score_case(case, scorecard)
    r.update({"score": sc["score"], "grade": sc["grade"], "scorecard_version": sc["scorecard_version"]})
    sim.wait(1)
    sim.move("DECISIONING", "T-17", "SYSTEM", "SCORE")
    sim.ev("SCORING_COMPLETED", "SYSTEM", {"score": sc["score"], "grade": sc["grade"], "pd": sc["pd"], "scorecard_version": sc["scorecard_version"]})
    dec = decide(case, sc, policy)
    r["policy_version"] = dec["policy_version"]
    sim.wait(1)
    o = dec["outcome"]
    if o == "DECLINED":
        decision_event(sim, dec, "AUTO", False, dec["options"], ctx)
        sim.move("DECLINED", "T-20", "SYSTEM", "DECIDE")
        for c in dec["reason_codes"]:
            if c.startswith("SF_"):
                sim.ev("STOP_FACTOR_TRIGGERED", "SYSTEM", {"reason_code": c, "policy_version": dec["policy_version"]})
        r["closed_at"] = iso(sim.t)
        return
    if o == "NEEDS_INFO":
        decision_event(sim, dec, "AUTO", False, [], ctx)
        state["auto_info_request_count"] += 1
        r["auto_info_request_count"] += 1
        r["info_request_count"] += 1
        items = [{"reason_code": i["reason_code"], "answer_type": i["answer_type"]} for i in dec["info_request_items"]]
        if client_answers(sim, rng, "POLICY", items, "T-21", policy, r["info_request_count"]):
            state["bank_statement_attached"] = True
            pipeline(sim, rng, src, req, state, ctx, scorecard, policy)
        return
    if o == "MANUAL_REVIEW":
        decision_event(sim, dec, "AUTO", False, [], ctx)
        r["manual_review_required"] = True
        state["manual_review_required"] = True
        if r["assignee"]:
            sim.move("IN_REVIEW", "T-23", "SYSTEM", "DECIDE")
            sim.ev("REVIEW_ASSIGNED", "SYSTEM", {"assignee_id": r["assignee"]})
        else:
            sim.move("MANUAL_REVIEW", "T-22", "SYSTEM", "DECIDE")
            sim.ev("MANUAL_REVIEW_QUEUED", "SYSTEM", {"reason_codes": dec["reason_codes"],
                                                       "review_due_at": iso(sim.t + timedelta(hours=policy["process"]["manual_review_sla_hours"]))})
        manual(sim, rng, src, req, state, ctx, scorecard, policy, dec)
        return
    decision_event(sim, dec, "AUTO", False, dec["options"], ctx)
    sim.move("OFFER_PENDING", "T-19", "SYSTEM", "DECIDE")
    offer(sim, rng, dec["outcome"], dec["options"], policy)


def decision_event(sim, dec, mode, override, options, ctx, actor="SYSTEM", login=None, outcome=None, codes=None):
    r = sim.rec
    outcome = outcome or dec["outcome"]
    codes = codes if codes is not None else dec["reason_codes"]
    did = str(uuid.uuid5(NS, f"decision-{sim.n}-{len(r['decisions'])}"))
    best = max(options, key=lambda o: float(o["amount"])) if options else None
    payload = {"decision_id": did, "outcome": outcome, "mode": mode, "reason_codes": codes,
               "policy_version": dec["policy_version"], "scorecard_version": r["scorecard_version"], "grade": r["grade"],
               "override": override, "requested_amount": r["amount"],
               "offered_amount_max": best["amount"] if best else None, "offered_term_months": best["term_months"] if best else None,
               "options_count": len(options),
               "time_from_submit_sec": int((sim.t - ctx["submitted_t"]).total_seconds())}
    sim.ev("DECISION_MADE", actor, payload, login)
    r["decisions"].append({"decision_id": did, "outcome": outcome, "mode": mode, "reason_codes": codes, "override": override,
                           "created_at": iso(sim.t), "decided_by": login})
    if outcome in ("APPROVED", "COUNTER_OFFER", "DECLINED") and r["decided_at"] is None:
        r["decided_at"] = iso(sim.t)


def manual(sim, rng, src, req, state, ctx, scorecard, policy, dec):
    r = sim.rec
    rec = dec.get("recommendation") or {}
    queued = sim.t
    due = queued + timedelta(hours=policy["process"]["manual_review_sla_hours"])
    returned = r["assignee"] is not None
    if not returned:
        if rng.random() < 0.02:
            sim.wait(rng.randint(600, 7200))
            r["cancel_reason"] = "CL_WITHDRAWN"
            sim.move("CANCELLED", "T-41", "CLIENT", "WITHDRAW")
            sim.ev("APPLICATION_CANCELLED", "CLIENT", {"cancel_reason": "CL_WITHDRAWN", "from_status": "MANUAL_REVIEW"})
            r["closed_at"] = iso(sim.t)
            return
        wait = rng.choice([rng.randint(300, 3600), rng.randint(3600, 4 * 3600), rng.randint(4 * 3600, 9 * 3600)])
        sim.wait(wait)
        uw = rng.choice(UNDERWRITERS)
        r["assignee"] = uw
        sim.move("IN_REVIEW", "T-25", "UNDERWRITER", "TAKE", uw)
        sim.ev("REVIEW_TAKEN", "UNDERWRITER", {"assignee_id": uw, "wait_sec": int((sim.t - queued).total_seconds())}, uw)
    uw = r["assignee"]
    sim.ev("APPLICATION_VIEWED", "UNDERWRITER", {"view_context": "QUEUE"}, uw)
    work = rng.randint(600, 3 * 3600)
    if sim.t + timedelta(seconds=work) > due and not r["sla_breached"]:
        t_save = sim.t
        sim.t = max(due, sim.t)
        if sim.t > REFERENCE_NOW:
            raise Stop()
        r["sla_breached"] = True
        sim.ev("REVIEW_SLA_BREACHED", "TIMER", {"review_due_at": iso(due), "assignee_id": uw})
        sim.t = t_save
    sim.wait(work)
    cid = str(uuid.uuid5(NS, f"comment-{sim.n}-{len(r['decisions'])}"))
    sim.ev("COMMENT_ADDED", "UNDERWRITER", {"comment_id": cid}, uw)
    rec_outcome = rec.get("outcome")
    x = rng.random()
    mismatch = "MR_DATA_MISMATCH" in dec["reason_codes"]
    if not returned and not ctx["uw_info_done"] and x < 0.15 and rec_outcome is not None:
        ctx["uw_info_done"] = True
        item = "NI_DATA_MISMATCH_EXPLANATION" if mismatch else ("NI_COLLATERAL_DOCUMENTS" if req["product_code"] == "INVESTMENT" else "NI_OTHER")
        decision_event(sim, dec, "MANUAL", False, [], ctx, "UNDERWRITER", uw, "NEEDS_INFO", [item])
        r["info_request_count"] += 1
        ans_type = "TEXT" if item != "NI_COLLATERAL_DOCUMENTS" else "DOCUMENT"
        if client_answers(sim, rng, "UNDERWRITER", [{"reason_code": item, "answer_type": ans_type}], "T-29", policy, r["info_request_count"]):
            pipeline(sim, rng, src, req, state, ctx, scorecard, policy)
        return
    if rec_outcome is None or rec_outcome == "DECLINED" or x < 0.32:
        code = "DCL_DATA_NOT_CONFIRMED" if mismatch and rng.random() < 0.6 else (
            "DCL_DOCUMENTS_NOT_PROVIDED" if rec_outcome is None else "DCL_UNDERWRITER_RISK")
        decision_event(sim, dec, "MANUAL", False, [], ctx, "UNDERWRITER", uw, "DECLINED", [code])
        sim.move("DECLINED", "T-30", "UNDERWRITER", "DECLINE", uw)
        r["closed_at"] = iso(sim.t)
        return
    options = rec["options"]
    outcome = rec_outcome
    codes = rec["reason_codes"] if outcome == "COUNTER_OFFER" else [c for c in rec["reason_codes"] if c == "CO_PRODUCT_ALTERNATIVE"]
    override = False
    if outcome == "COUNTER_OFFER" and x > 0.88:
        override = True
        outcome = "APPROVED"
        p = dict(options[0])
        rate = rate_for(policy, r["product_code"], r["grade"])
        totals = schedule_totals(r["amount"], rate, r["term_months"])
        p.update({"option_type": "UNDERWRITER_TERMS", "product_code": r["product_code"], "amount": r["amount"], "term_months": r["term_months"], "rate_percent": str(rate),
                  "tranche_max_term_months": None, "monthly_payment": str(totals["monthly_payment"]), "total_payment": str(totals["total_payment"]),
                  "overpayment": str(totals["overpayment"]), "recommended": True})
        options = [p]
        codes = ["CO_UNDERWRITER_TERMS"]
    four_eyes = override or any(float(o["amount"]) > float(policy["authority"]["underwriter_authority_limit"]) for o in options)
    if four_eyes:
        sim.move("PENDING_RISK_APPROVAL", "T-28", "UNDERWRITER", "APPROVE" if outcome == "APPROVED" else "MAKE_COUNTER_OFFER", uw)
        did = str(uuid.uuid5(NS, f"proposal-{sim.n}"))
        trig = "OVERRIDE" if override else "AUTHORITY_LIMIT"
        sim.ev("FOUR_EYES_REQUESTED", "UNDERWRITER", {"decision_id": did, "proposed_by": uw, "confirmed_by": None, "trigger": trig}, uw)
        sim.wait(rng.randint(900, 3 * 3600))
        if rng.random() < 0.85:
            sim.ev("FOUR_EYES_APPROVED", "RISK_MANAGER", {"decision_id": did, "proposed_by": uw, "confirmed_by": RISK, "trigger": trig}, RISK)
            decision_event(sim, dec, "MANUAL", override, options, ctx, "RISK_MANAGER", RISK, outcome, codes)
            sim.move("OFFER_PENDING", "T-31", "RISK_MANAGER", "CONFIRM_DECISION", RISK)
            offer(sim, rng, outcome, options, policy)
            return
        sim.ev("FOUR_EYES_REJECTED", "RISK_MANAGER", {"decision_id": did, "proposed_by": uw, "confirmed_by": RISK, "trigger": trig}, RISK)
        sim.move("IN_REVIEW", "T-32", "RISK_MANAGER", "RETURN_DECISION", RISK)
        sim.wait(rng.randint(900, 2 * 3600))
        options, outcome, codes, override = rec["options"], rec_outcome, rec["reason_codes"], False
        if any(float(o["amount"]) > float(policy["authority"]["underwriter_authority_limit"]) for o in options):
            decision_event(sim, dec, "MANUAL", False, [], ctx, "UNDERWRITER", uw, "DECLINED", ["DCL_UNDERWRITER_RISK"])
            sim.move("DECLINED", "T-30", "UNDERWRITER", "DECLINE", uw)
            r["closed_at"] = iso(sim.t)
            return
    decision_event(sim, dec, "MANUAL", override, options, ctx, "UNDERWRITER", uw, outcome, codes)
    sim.move("OFFER_PENDING", "T-27", "UNDERWRITER", "APPROVE" if outcome == "APPROVED" else "MAKE_COUNTER_OFFER", uw)
    offer(sim, rng, outcome, options, policy)


def offer(sim, rng, outcome, options, policy):
    r = sim.rec
    oid = str(uuid.uuid5(NS, f"offer-{sim.n}"))
    expires = sim.t + timedelta(days=policy["process"]["offer_ttl_days"])
    sim.ev("OFFER_ISSUED", "SYSTEM", {"offer_id": oid, "options": [{k: o[k] for k in ("option_type", "product_code", "amount", "term_months",
                                                                                     "rate_percent", "monthly_payment")} for o in options],
                                       "expires_at": iso(expires)})
    r["offers"].append({"offer_id": oid, "outcome": outcome, "options": options, "expires_at": iso(expires)})
    issued = sim.t
    x = rng.random()
    accept_p, decline_p = (0.80, 0.10) if outcome == "APPROVED" else (0.58, 0.22)
    if x < accept_p:
        sim.wait(rng.choice([rng.randint(300, 3600), rng.randint(3600, 86400), rng.randint(86400, 3 * 86400)]))
        rec = [o for o in options if o["recommended"]]
        others = [o for o in options if not o["recommended"]]
        chosen = rec[0] if (rng.random() < 0.65 or not others) else rng.choice(others)
        sim.move("OFFER_ACCEPTED", "T-33", "CLIENT", "ACCEPT_OFFER")
        sim.ev("OFFER_ACCEPTED", "CLIENT", {"offer_id": oid, "option_id": f"{oid}-{options.index(chosen) + 1}", "option_type": chosen["option_type"],
                                             "product_code": chosen["product_code"], "amount": chosen["amount"], "term_months": chosen["term_months"],
                                             "decision_sec": int((sim.t - issued).total_seconds())})
        r.update({"final_product_code": chosen["product_code"], "final_amount": chosen["amount"], "final_term_months": chosen["term_months"],
                  "final_rate_percent": chosen["rate_percent"], "final_monthly_payment": chosen["monthly_payment"]})
        sim.wait(rng.randint(10, 60))
        docs = ["CREDIT_AGREEMENT", "PAYMENT_SCHEDULE"] + (["GUARANTEE_AGREEMENT"] if r["applicant_type"] == "LEGAL_ENTITY" else []) + \
               (["PLEDGE_AGREEMENT"] if chosen["product_code"] == "INVESTMENT" else [])
        sim.move("SIGNING", "T-36", "SYSTEM", "PREPARE_DOCUMENTS")
        sim.ev("DOCUMENTS_PREPARED", "SYSTEM", {"document_types": docs, "edo_operation_id": f"edo-{sim.n:06d}"})
        y = rng.random()
        if y < 0.94:
            sim.wait(rng.randint(60, 1800))
            code_id = str(uuid.uuid5(NS, f"code-{sim.n}"))
            sim.ev("SIGNING_CODE_ISSUED", "CLIENT", {"signing_code_id": code_id, "expires_at": iso(sim.t + timedelta(minutes=5))})
            if rng.random() < 0.05:
                sim.wait(rng.randint(20, 90))
                sim.ev("SIGNING_CODE_REJECTED", "CLIENT", {"signing_code_id": code_id, "attempt": 1, "reason": "WRONG"})
            sim.wait(rng.randint(20, 200))
            sim.move("SIGNED", "T-39", "CLIENT", "SIGN")
            sim.ev("DOCUMENTS_SIGNED", "CLIENT", {"signing_code_id": code_id, "documents_sha256": [f"sha256-{sim.n:06d}-{k}" for k in range(len(docs))]})
            sim.wait(rng.randint(5, 40))
            if rng.random() < 0.01:
                sim.move("PROCESSING_ERROR", "T-43", "SYSTEM", "ISSUE_LOAN")
                sim.ev("PROCESSING_FAILED", "SYSTEM", {"failed_stage": "SIGNED", "last_error_code": "ABS_FAILED"})
                sim.wait(rng.randint(1800, 3 * 3600))
                uw = rng.choice(UNDERWRITERS)
                sim.move("SIGNED", "T-44", "UNDERWRITER", "RETRY_PROCESSING", uw)
                sim.ev("PROCESSING_RETRIED", "UNDERWRITER", {"failed_stage": "SIGNED"}, uw)
                sim.wait(rng.randint(5, 40))
            line = chosen["product_code"] == "CREDIT_LINE"
            sim.move("ISSUED", "T-42", "SYSTEM", "ISSUE_LOAN")
            sim.ev("LOAN_ISSUED", "SYSTEM", {"product_code": chosen["product_code"], "amount": chosen["amount"], "term_months": chosen["term_months"],
                                              "rate_percent": chosen["rate_percent"], "abs_operation_id": f"abs-{sim.n:06d}",
                                              "operation_type": "CREDIT_LINE_LIMIT" if line else "DISBURSEMENT"})
            r["issued_at"] = iso(sim.t)
            r["closed_at"] = iso(sim.t)
        elif y < 0.97:
            sim.wait(rng.randint(600, 86400))
            sim.move("OFFER_DECLINED", "T-38", "CLIENT", "DECLINE_OFFER")
            sim.ev("OFFER_DECLINED", "CLIENT", {"offer_id": oid, "decline_reason_code": "OD_FOUND_ELSEWHERE"})
            r["closed_at"] = iso(sim.t)
        else:
            sim.t = expires
            if sim.t > REFERENCE_NOW:
                raise Stop()
            sim.move("OFFER_EXPIRED", "T-40", "TIMER", "OFFER_EXPIRY")
            sim.ev("OFFER_EXPIRED", "TIMER", {"offer_id": oid, "stage": "SIGNING"})
            r["closed_at"] = iso(sim.t)
        return
    if x < accept_p + decline_p:
        sim.wait(rng.randint(600, 2 * 86400))
        reason = rng.choice(["OD_RATE_TOO_HIGH", "OD_PAYMENT_TOO_HIGH", "OD_AMOUNT_TOO_LOW", "OD_FOUND_ELSEWHERE", "OD_NOT_NEEDED", None])
        sim.move("OFFER_DECLINED", "T-34", "CLIENT", "DECLINE_OFFER")
        sim.ev("OFFER_DECLINED", "CLIENT", {"offer_id": oid, "decline_reason_code": reason})
        r["closed_at"] = iso(sim.t)
        return
    sim.t = expires
    if sim.t > REFERENCE_NOW:
        raise Stop()
    sim.move("OFFER_EXPIRED", "T-35", "TIMER", "OFFER_EXPIRY")
    sim.ev("OFFER_EXPIRED", "TIMER", {"offer_id": oid, "stage": "OFFER_PENDING"})
    r["closed_at"] = iso(sim.t)
