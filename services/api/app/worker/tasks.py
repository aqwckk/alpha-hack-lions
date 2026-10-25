"""Pipeline tasks executed by the worker: COMPLETENESS_CHECK, ENRICH, SCORE, DECIDE, PREPARE_DOCUMENTS, ISSUE_LOAN.

Every task re-reads the application, does nothing if the status moved on (cancelled, retried by a
person), performs external calls outside of a database transaction and then applies the transition
with the version it read: a concurrent client command wins and the task result is discarded.
"""

from __future__ import annotations

import logging
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import session_scope
from ..domain import policy as policy_engine
from ..domain import scoring as scoring_engine
from ..domain.configs import ConfigError, get_registry
from ..domain.dictionaries import (
    DOCUMENT_TYPES,
    EXTRA_REASON_CODES,
    fmt_date,
    fmt_money,
    render,
)
from ..domain.money import add_months, money, payment_schedule
from ..enums import JobKind, Outcome, Role, Status, Trigger
from ..models import (
    Application,
    Consent,
    Decision,
    Document,
    DocumentPackage,
    Event,
    GeneratedDocument,
    IntegrationRequest,
    Loan,
    OfferOption,
    ScoringResult,
    SourceSnapshot,
    Signature,
    User,
)
from ..services import integrations
from ..services.client_commands import _save_snapshot
from ..services.core import (
    Actor,
    apply_transition,
    due,
    emit,
    enqueue,
    notify,
    notify_role,
    utcnow,
)
from ..services.params import process_params
from ..services.schedules import package_schedule
from ..services.staff_commands import (
    create_info_request,
    create_offer,
    decision_made_payload,
)

log = logging.getLogger("app.worker")
MSK = ZoneInfo("Europe/Moscow")

ERROR_TRANSITION = {
    Status.SUBMITTED: "T-09",
    Status.ENRICHMENT: "T-16",
    Status.SCORING: "T-18",
    Status.DECISIONING: "T-24",
    Status.OFFER_ACCEPTED: "T-37",
    Status.SIGNED: "T-43",
}


class StaleTask(Exception):
    """The application is no longer in the status the task was created for."""


def _load(session: Session, application_id: uuid.UUID, expected: str) -> Application:
    app = session.get(Application, application_id)
    if app is None or app.status != expected:
        raise StaleTask
    return app


def _locked_app(session: Session, application_id: uuid.UUID, expected: str, version: int | None = None) -> Application:
    app = session.execute(select(Application).where(Application.id == application_id).with_for_update()).scalar_one_or_none()
    if app is None or app.status != expected or (version is not None and app.version != version):
        raise StaleTask
    return app


def _remember_response(key: str, response: dict[str, Any]) -> dict[str, Any]:
    with session_scope() as session:
        intent = session.execute(select(IntegrationRequest).where(IntegrationRequest.idempotency_key == key).with_for_update()).scalar_one()
        if intent.response is None:
            intent.response = response
        return intent.response


def fail_stage(session: Session, app: Application, actor: Actor, error_code: str) -> None:
    """Technical failure: PROCESSING_ERROR with failed_stage, never a false credit decline."""
    stage = Status(app.status)
    tid = ERROR_TRANSITION[stage]
    trigger = Trigger.ENRICHMENT_FAILED if stage == Status.ENRICHMENT else Trigger.TASK_FAILED
    apply_transition(session, app, tid, actor, trigger=trigger, expected_version=app.version, changes={"failed_stage": stage.value, "last_error_code": error_code, "next_retry_at": None})
    emit(session, "PROCESSING_FAILED", actor, application=app, payload={"failed_stage": stage.value, "last_error_code": error_code})
    notify_role(session, Role.UNDERWRITER, "NTF_EMP_PROCESSING_ERROR", application=app, failed_stage=stage.value)


def msk_today() -> str:
    return datetime.now(MSK).date().isoformat()


# Completeness check


def completeness_check(job: dict[str, Any], actor: Actor) -> None:
    with session_scope() as session:
        app = _load(session, job["application_id"], Status.SUBMITTED)
        pol = get_registry().policy_content()
        product = pol["products"][app.product_code]
        params = process_params()
        present = set(session.execute(select(Document.document_type).where(Document.application_id == app.id, Document.deleted_at.is_(None))).scalars())
        missing = [d for d in product["required_documents"] if d not in present]
        attempt = 1 + session.execute(
            select(func.count()).select_from(Event).where(Event.application_id == app.id, Event.event_type.in_(["COMPLETENESS_PASSED", "COMPLETENESS_FAILED"]))
        ).scalar_one()
        if not missing:
            apply_transition(session, app, "T-06", actor, trigger=Trigger.COMPLETENESS_PASSED, expected_version=app.version)
            emit(session, "COMPLETENESS_PASSED", actor, application=app, payload={"attempt": attempt})
            enqueue(session, JobKind.ENRICH, app, correlation_id=actor.correlation_id)
            return
        emit(session, "COMPLETENESS_FAILED", actor, application=app, payload={"missing_items": missing})
        if app.auto_info_request_count < params.max_auto_info_cycles:
            apply_transition(
                session, app, "T-07", actor, trigger=Trigger.COMPLETENESS_FAILED, expected_version=app.version,
                changes={"auto_info_request_count": app.auto_info_request_count + 1, "info_request_count": app.info_request_count + 1},
            )
            template = EXTRA_REASON_CODES["NI_MISSING_DOCUMENTS"]
            items = [
                {
                    "reason_code": "NI_MISSING_DOCUMENTS", "answer_type": "DOCUMENT", "field_name": None, "document_type": d,
                    "client_text": render(template["client_text"], {"document_name": DOCUMENT_TYPES[d]["title"], "document_purpose": DOCUMENT_TYPES[d]["purpose"]}),
                    "employee_text": render(template["employee_text"], {"document_type": d}), "required": True,
                }
                for d in missing
            ]
            create_info_request(session, app, actor, source="COMPLETENESS_CHECK", items=items, decision_id=None)
            return
        now = utcnow()
        apply_transition(
            session, app, "T-08", actor, trigger=Trigger.COMPLETENESS_FAILED, expected_version=app.version,
            changes={"manual_review_required": True, "manual_review_reasons": ["MR_INFO_CYCLES_EXCEEDED"], "review_queued_at": now, "review_due_at": due(params.review_sla_seconds)},
        )
        emit(session, "MANUAL_REVIEW_QUEUED", actor, application=app, payload={"reason_codes": ["MR_INFO_CYCLES_EXCEEDED"], "review_due_at": app.review_due_at.isoformat()})


# Enrichment


def _applicable_sources(app: Application) -> list[str]:
    sources = ["REGISTRY", "FNS"]
    if app.applicant_type == "LEGAL_ENTITY":
        sources.append("FINANCIAL_STATEMENTS")
    return sources + ["CREDIT_BUREAU", "BANK_TURNOVER"]


def _cached(session: Session, app: Application, source: str) -> SourceSnapshot | None:
    consent = _bureau_consent(session, app) if source == "CREDIT_BUREAU" else None
    if source == "CREDIT_BUREAU" and consent is None:
        return None
    query = (
        select(SourceSnapshot)
        .where(
            SourceSnapshot.application_id == app.id, SourceSnapshot.source == source, SourceSnapshot.inn == app.applicant_inn,
            SourceSnapshot.outcome.in_(["SUCCESS", "NO_DATA"]), SourceSnapshot.valid_until > utcnow(),
        )
    )
    if consent is not None:
        query = query.where(SourceSnapshot.requested_at >= consent.granted_at)
    return session.execute(query.order_by(SourceSnapshot.responded_at.desc()).limit(1)).scalar_one_or_none()


def _bureau_consent(session: Session, app: Application) -> Consent | None:
    now = utcnow()
    return session.execute(
        select(Consent).where(
            Consent.application_id == app.id, Consent.consent_type == "CONSENT_CREDIT_BUREAU",
            Consent.subject_inn == app.applicant_inn, Consent.revoked_at.is_(None),
            Consent.granted_at <= now, Consent.expires_at > now,
        ).order_by(Consent.granted_at.desc()).limit(1)
    ).scalar_one_or_none()


def _fetch_with_retries(source: str, inn: str, consent: dict | None, correlation_id: str) -> list[integrations.SourceResult]:
    s = get_settings()
    delays = s.fast_retry_delays
    attempts: list[integrations.SourceResult] = []
    for i in range(max(s.source_attempts, 1)):
        res = integrations.fetch_source(source, inn, timeout=s.source_timeout_seconds, correlation_id=correlation_id, consent=consent)
        attempts.append(res)
        if res.ok:
            break
        if i < s.source_attempts - 1:
            time.sleep(delays[min(i, len(delays) - 1)] if delays else 0)
    return attempts


def enrich(job: dict[str, Any], actor: Actor) -> None:
    s = get_settings()
    started = utcnow()
    with session_scope() as session:
        app = _load(session, job["application_id"], Status.ENRICHMENT)
        version, inn = app.version, app.applicant_inn
        sources = _applicable_sources(app)
        c = _bureau_consent(session, app)
        if c is None:
            fail_stage(session, app, actor, "CONSENT_MISSING")
            return
        consent_id = c.id
        consent = {"consent_id": str(c.id), "subject_inn": c.subject_inn, "granted_at": c.granted_at.isoformat(), "expires_at": c.expires_at.isoformat(), "text_version": c.text_version}
        cached = {src: snap.id for src in sources if (snap := _cached(session, app, src)) is not None}
        prior_attempts = dict(
            session.execute(
                select(SourceSnapshot.source, func.count()).where(SourceSnapshot.application_id == app.id, SourceSnapshot.stage == "ENRICH").group_by(SourceSnapshot.source)
            ).all()
        )
    to_fetch = [src for src in sources if src not in cached]
    results: dict[str, list[integrations.SourceResult]] = {}
    if to_fetch:
        with ThreadPoolExecutor(max_workers=len(to_fetch)) as pool:
            futures = {src: pool.submit(_fetch_with_retries, src, inn, consent if src == "CREDIT_BUREAU" else None, actor.correlation_id) for src in to_fetch}
            results = {src: f.result() for src, f in futures.items()}

    with session_scope() as session:
        app = session.execute(select(Application).where(Application.id == job["application_id"]).with_for_update()).scalar_one_or_none()
        if app is None or app.status != Status.ENRICHMENT or app.version != version:
            raise StaleTask
        c = _bureau_consent(session, app)
        if c is None or c.id != consent_id:
            fail_stage(session, app, actor, "CONSENT_MISSING")
            return
        for src in sources:
            if src in cached:
                emit(session, "SOURCE_REQUEST_SUCCEEDED", actor, application=app, payload={"source": src, "attempt": 0, "latency_ms": 0, "from_cache": True})
                continue
            for i, res in enumerate(results[src]):
                attempt = prior_attempts.get(src, 0) + i + 1
                _save_snapshot(session, app, res, stage="ENRICH", attempt=attempt, inn=inn)
                if res.ok:
                    emit(session, "SOURCE_REQUEST_SUCCEEDED", actor, application=app, payload={"source": src, "attempt": attempt, "latency_ms": res.duration_ms, "from_cache": False})
                else:
                    emit(session, "SOURCE_REQUEST_FAILED", actor, application=app, payload={"source": src, "attempt": attempt, "error_code": res.error_code, "latency_ms": res.duration_ms})
        failed = [src for src in to_fetch if not results[src][-1].ok]
        if not failed:
            apply_transition(session, app, "T-13", actor, trigger=Trigger.ENRICHMENT_COMPLETED, expected_version=version, changes={"next_retry_at": None})
            emit(session, "ENRICHMENT_COMPLETED", actor, application=app, payload={"sources": sources, "duration_ms": int((utcnow() - started).total_seconds() * 1000), "retries_total": app.enrichment_retry_count})
            enqueue(session, JobKind.SCORE, app, correlation_id=actor.correlation_id)
            return
        last_error = results[failed[0]][-1].error_code or "SOURCE_HTTP_5XX"
        schedule = s.retry_schedule
        if app.enrichment_retry_count < len(schedule):
            retry_number = app.enrichment_retry_count + 1
            next_at = due(schedule[app.enrichment_retry_count])
            apply_transition(session, app, "T-14", actor, trigger=Trigger.SOURCES_UNAVAILABLE, expected_version=version, changes={"next_retry_at": next_at, "last_error_code": last_error})
            emit(session, "ENRICHMENT_RETRY_SCHEDULED", actor, application=app, payload={"failed_sources": failed, "retry_number": retry_number, "next_retry_at": next_at.isoformat()})
            if retry_number == 1:
                notify(session, app.client_user_id, "NTF_CHECK_DELAYED", application=app)
            return
        emit(session, "ENRICHMENT_FAILED", actor, application=app, payload={"failed_sources": failed, "retries_total": app.enrichment_retry_count, "last_error_code": last_error})
        fail_stage(session, app, actor, last_error)


# Scoring and decision


class MissingSourceData(Exception):
    """Missing/expired evidence is a technical failure, not a negative source answer."""


def build_case(session: Session, app: Application) -> dict[str, Any]:
    sources: dict[str, Any] = {}
    for src in _applicable_sources(app):
        snap = _cached(session, app, src)
        if snap is None or (snap.outcome == "SUCCESS" and snap.response is None):
            raise MissingSourceData(src)
        sources[src] = snap.response
    if sources["REGISTRY"] is None:
        sources["REGISTRY"] = {"found": False}
    if app.applicant_type != "LEGAL_ENTITY":
        sources["FINANCIAL_STATEMENTS"] = None
    elif sources["FINANCIAL_STATEMENTS"] is None:
        sources["FINANCIAL_STATEMENTS"] = {"found": False}
    if sources["CREDIT_BUREAU"] is None:
        sources["CREDIT_BUREAU"] = {"no_record": True}
    if sources["BANK_TURNOVER"] is None:
        sources["BANK_TURNOVER"] = {"has_account": False, "months_available": 0, "inflow_by_month": [None] * 12, "avg_monthly_inflow_12m": "0.00", "compliance_flag": "NONE"}
    has_statement = session.execute(
        select(func.count()).select_from(Document).where(Document.application_id == app.id, Document.document_type == "BANK_STATEMENT", Document.deleted_at.is_(None))
    ).scalar_one() > 0

    def m(v: Decimal | None) -> str | None:
        return None if v is None else str(money(v))

    return {
        "as_of_date": msk_today(),
        "application": {
            "product_code": app.product_code, "purpose": app.purpose, "amount": m(app.amount), "term_months": app.term_months,
            "applicant_type": app.applicant_type, "applicant_inn": app.applicant_inn,
            "monthly_revenue_declared": m(app.monthly_revenue_declared), "existing_monthly_payments_declared": m(app.existing_monthly_payments_declared),
            "collateral_value": m(app.collateral_value), "collateral_type": app.collateral_type,
        },
        "state": {"auto_info_request_count": app.auto_info_request_count, "manual_review_required": app.manual_review_required, "bank_statement_attached": has_statement},
        "sources": sources,
    }


def score(job: dict[str, Any], actor: Actor) -> None:
    with session_scope() as session:
        app = _load(session, job["application_id"], Status.SCORING)
        try:
            scorecard, _ = get_registry().require()
        except ConfigError:
            fail_stage(session, app, actor, "CONFIG_LOAD_FAILED")
            return
        try:
            case = build_case(session, app)
        except MissingSourceData:
            fail_stage(session, app, actor, "SOURCE_INVALID_RESPONSE")
            return
        result = scoring_engine.score(case, scorecard.content)
        sr = ScoringResult(
            id=uuid.uuid4(), application_id=app.id, score=result["score"], grade=result["grade"], pd=Decimal(result["pd"]), features=result["features"],
            factor_contributions=result["factor_contributions"], scoring_input=case, scorecard_version=scorecard.version, scorecard_sha256=scorecard.sha256,
            as_of_date=datetime.fromisoformat(case["as_of_date"]).date(), calculated_at=utcnow(),
        )
        session.add(sr)
        apply_transition(session, app, "T-17", actor, trigger=Trigger.SCORING_COMPLETED, expected_version=app.version, changes={"score": result["score"], "grade": result["grade"]})
        emit(session, "SCORING_COMPLETED", actor, application=app, payload={"score": result["score"], "grade": result["grade"], "pd": result["pd"], "scorecard_version": scorecard.version})
        enqueue(session, JobKind.DECIDE, app, correlation_id=actor.correlation_id)


def decide(job: dict[str, Any], actor: Actor) -> None:
    with session_scope() as session:
        app = _load(session, job["application_id"], Status.DECISIONING)
        try:
            _, policy = get_registry().require()
        except ConfigError:
            fail_stage(session, app, actor, "CONFIG_LOAD_FAILED")
            return
        sr = session.execute(select(ScoringResult).where(ScoringResult.application_id == app.id).order_by(ScoringResult.calculated_at.desc()).limit(1)).scalar_one()
        case = dict(sr.scoring_input)
        try:
            case["state"] = build_case(session, app)["state"]
        except MissingSourceData:
            fail_stage(session, app, actor, "SOURCE_INVALID_RESPONSE")
            return
        result = policy_engine.decide(case, {"score": sr.score, "grade": sr.grade, "scorecard_version": sr.scorecard_version}, policy.content)
        decision = Decision(
            id=uuid.uuid4(), application_id=app.id, scoring_result_id=sr.id, outcome=result["outcome"], mode="AUTO", status="FINAL",
            reason_codes=result["reason_codes"], reason_details=result["reason_details"], rules_path=result["rules_path"], values=result["values"],
            recommendation=result["recommendation"], proposed_options=result["options"] or None, override=False, scorecard_version=sr.scorecard_version,
            policy_version=policy.version, policy_sha256=policy.sha256, grade=sr.grade, created_at=utcnow(),
        )
        session.add(decision)
        session.flush()
        outcome = Outcome(result["outcome"])
        params = process_params()
        now = utcnow()
        if outcome in (Outcome.APPROVED, Outcome.COUNTER_OFFER):
            apply_transition(session, app, "T-19", actor, trigger=Trigger.POLICY_OFFER, expected_version=app.version, changes={"decided_at": now})
            emit(session, "DECISION_MADE", actor, application=app, payload=decision_made_payload(app, decision, result["options"]))
            offer = create_offer(session, app, decision, result["options"], actor)
            app.current_offer_id = offer.id
        elif outcome == Outcome.DECLINED:
            apply_transition(session, app, "T-20", actor, trigger=Trigger.POLICY_DECLINED, expected_version=app.version, changes={"decided_at": now})
            for code in result["reason_codes"]:
                if code.startswith("SF_"):
                    emit(session, "STOP_FACTOR_TRIGGERED", actor, application=app, payload={"reason_code": code, "policy_version": policy.version})
            emit(session, "DECISION_MADE", actor, application=app, payload=decision_made_payload(app, decision, []))
            notify(session, app.client_user_id, "NTF_DECISION_DECLINED", application=app)
        elif outcome == Outcome.NEEDS_INFO:
            apply_transition(
                session, app, "T-21", actor, trigger=Trigger.POLICY_NEEDS_INFO, expected_version=app.version,
                changes={"auto_info_request_count": app.auto_info_request_count + 1, "info_request_count": app.info_request_count + 1},
            )
            emit(session, "DECISION_MADE", actor, application=app, payload=decision_made_payload(app, decision, []))
            text = render(policy.content["reason_codes"]["NI_INCOME_NOT_CONFIRMED"]["client_text"], {})
            items = []
            for tpl in result["info_request_items"]:
                is_doc = tpl["answer_type"] == "DOCUMENT"
                items.append({
                    "reason_code": tpl["reason_code"], "answer_type": tpl["answer_type"], "field_name": tpl.get("field_name"), "document_type": tpl.get("document_type"),
                    "client_text": text if is_doc else "Проверьте среднюю выручку в месяц за последние 12 месяцев и при необходимости исправьте ее.",
                    "employee_text": policy.content["reason_codes"][tpl["reason_code"]]["employee_text"], "required": bool(tpl.get("required", True)),
                })
            create_info_request(session, app, actor, source="POLICY", items=items, decision_id=decision.id)
        else:
            assignee = session.get(User, app.assignee_id) if app.assignee_id else None
            reasons = result["reason_codes"]
            if assignee is not None and assignee.is_active:
                apply_transition(
                    session, app, "T-23", actor, trigger=Trigger.POLICY_MANUAL_REVIEW, expected_version=app.version,
                    changes={"review_due_at": due(params.review_sla_seconds), "manual_review_reasons": reasons, "manual_review_required": True, "sla_breached": False},
                )
                emit(session, "DECISION_MADE", actor, application=app, payload=decision_made_payload(app, decision, []))
                emit(session, "REVIEW_ASSIGNED", actor, application=app, payload={"assignee_id": str(assignee.id)})
                notify(session, assignee.id, "NTF_EMP_INFO_PROVIDED", application=app)
            else:
                apply_transition(
                    session, app, "T-22", actor, trigger=Trigger.POLICY_MANUAL_REVIEW, expected_version=app.version,
                    changes={"assignee_id": None, "manual_review_required": True, "manual_review_reasons": reasons, "review_queued_at": now, "review_due_at": due(params.review_sla_seconds), "sla_breached": False},
                )
                emit(session, "DECISION_MADE", actor, application=app, payload=decision_made_payload(app, decision, []))
                emit(session, "MANUAL_REVIEW_QUEUED", actor, application=app, payload={"reason_codes": reasons, "review_due_at": app.review_due_at.isoformat()})


# Documents and disbursement


def _with_retries(fn, attempts: int):
    s = get_settings()
    last: Exception | None = None
    for i in range(max(attempts, 1)):
        try:
            return fn()
        except integrations.OperationError as exc:
            last = exc
            if exc.http_status is not None and 400 <= exc.http_status < 500:
                break
            if i < attempts - 1:
                delays = s.fast_retry_delays
                time.sleep(delays[min(i, len(delays) - 1)] if delays else 0)
    raise last  # type: ignore[misc]


def prepare_documents(job: dict[str, Any], actor: Actor) -> None:
    s = get_settings()
    with session_scope() as session:
        app = _locked_app(session, job["application_id"], Status.OFFER_ACCEPTED)
        version = app.version
        key = f"EDO:{app.id}:{app.final_option_id}"
        intent = session.get(IntegrationRequest, key)
        if intent is None:
            option = session.get(OfferOption, app.final_option_id)
            pol = get_registry().policy_content()
            product = pol["products"][option.product_code]
            reg = app.registry_data or {}
            founders = reg.get("founders") or []
            guarantor = max(founders, key=lambda f: Decimal(str(f.get("share_percent") or 0)))["name"] if founders else reg.get("director_full_name")
            payment_term = option.tranche_max_term_months or option.term_months
            first_payment = add_months(datetime.fromisoformat(msk_today()).date(), 1)
            docs = ["CREDIT_AGREEMENT", "PAYMENT_SCHEDULE"]
            if option.requires_owner_guarantee:
                docs.append("GUARANTEE_AGREEMENT")
            if option.requires_collateral:
                docs.append("PLEDGE_AGREEMENT")
            body = {
                "application_id": str(app.id),
                "application_number": app.application_number,
                "applicant": {"inn": app.applicant_inn, "name": app.company_short_name or app.applicant_inn, "applicant_type": app.applicant_type, "guarantor_name": guarantor if app.applicant_type == "LEGAL_ENTITY" else None},
                "terms": {
                    "product_code": option.product_code, "product_name": product["name"], "amount": str(option.amount), "term_months": option.term_months,
                    "rate_percent": str(option.rate_percent), "monthly_payment": str(option.monthly_payment), "total_payment": str(option.total_payment),
                    "overpayment": str(option.overpayment), "tranche_max_term_months": option.tranche_max_term_months,
                },
                "documents": docs,
                "schedule": payment_schedule(option.amount, option.rate_percent, payment_term, first_payment),
                "collateral": {"type": app.collateral_type, "description": app.collateral_description, "value": str(app.collateral_value) if app.collateral_value else None} if option.requires_collateral else None,
            }
            intent = IntegrationRequest(idempotency_key=key, application_id=app.id, system="EDO", request=body)
            session.add(intent)
        body, package = intent.request, intent.response
        option_id = app.final_option_id

    try:
        if package is None:
            package = _with_retries(lambda: integrations.create_document_package(body, idempotency_key=key, correlation_id=actor.correlation_id), s.operation_attempts)
            package = _remember_response(key, package)
    except integrations.OperationError:
        with session_scope() as session:
            app = _locked_app(session, job["application_id"], Status.OFFER_ACCEPTED, version)
            fail_stage(session, app, actor, "EDO_FAILED")
        return
    with session_scope() as session:
        app = _locked_app(session, job["application_id"], Status.OFFER_ACCEPTED, version)
        pkg = DocumentPackage(id=uuid.uuid4(), application_id=app.id, offer_option_id=option_id, external_package_id=package["package_id"], edo_operation_id=package["edo_operation_id"], contract_number=package["contract_number"], status="READY_FOR_SIGNING", created_at=utcnow())
        session.add(pkg)
        session.flush()
        for d in package["documents"]:
            session.add(GeneratedDocument(id=uuid.uuid4(), package_id=pkg.id, document_type=d["document_type"], title=d["title"], content_type=d["content_type"], content=d["content"], sha256=d["sha256"]))
        apply_transition(session, app, "T-36", actor, trigger=Trigger.DOCUMENTS_PREPARED, expected_version=version)
        emit(session, "DOCUMENTS_PREPARED", actor, application=app, payload={"document_types": [d["document_type"] for d in package["documents"]], "edo_operation_id": package["edo_operation_id"]})
        notify(session, app.client_user_id, "NTF_DOCUMENTS_READY", application=app)


def issue_loan(job: dict[str, Any], actor: Actor) -> None:
    s = get_settings()
    with session_scope() as session:
        app = _locked_app(session, job["application_id"], Status.SIGNED)
        version = app.version
        key = str(app.id)
        intent = session.get(IntegrationRequest, key)
        if intent is None:
            signature = session.execute(select(Signature).where(Signature.application_id == app.id)).scalar_one()
            pkg = session.get(DocumentPackage, signature.package_id)
            schedule = package_schedule(session, pkg)
            operation = "CREDIT_LINE_LIMIT" if app.final_product_code == "CREDIT_LINE" else "DISBURSEMENT"
            body = {
                "application_id": str(app.id), "operation_type": operation, "borrower_inn": app.applicant_inn, "product_code": app.final_product_code,
                "amount": str(app.final_amount), "term_months": app.final_term_months, "rate_percent": str(app.final_rate_percent), "monthly_payment": str(app.final_monthly_payment),
                "contract_number": pkg.contract_number, "schedule": schedule, "first_payment_date": schedule[0]["date"],
            }
            intent = IntegrationRequest(idempotency_key=key, application_id=app.id, system="ABS", request=body)
            session.add(intent)
        body, op = intent.request, intent.response
        operation = body["operation_type"]

    try:
        # the ABS idempotency key is the application id: a repeated task or a manual retry never issues twice
        if op is None:
            op = _with_retries(lambda: integrations.issue_loan(body, idempotency_key=key, correlation_id=actor.correlation_id), s.operation_attempts)
            if op["contract_number"] != body["contract_number"] or op["first_payment_date"] != body["first_payment_date"] or op["schedule"] != body["schedule"]:
                raise integrations.OperationError("INVALID_RESPONSE", "ABS changed the signed terms")
            op = _remember_response(key, op)
    except integrations.OperationError:
        with session_scope() as session:
            app = _locked_app(session, job["application_id"], Status.SIGNED, version)
            fail_stage(session, app, actor, "ABS_FAILED")
        return
    with session_scope() as session:
        app = _locked_app(session, job["application_id"], Status.SIGNED, version)
        issued_at = datetime.fromisoformat(op["issued_at"].replace("Z", "+00:00"))
        existing = session.execute(select(Loan).where(Loan.application_id == app.id)).scalar_one_or_none()
        if existing is None:
            session.add(Loan(
                id=uuid.uuid4(), application_id=app.id, contract_number=op["contract_number"], account_number_masked=op["account_number_masked"],
                product_code=app.final_product_code, operation_type=operation, amount=app.final_amount, rate_percent=app.final_rate_percent,
                term_months=app.final_term_months, monthly_payment=app.final_monthly_payment, issued_at=issued_at,
                first_payment_date=datetime.fromisoformat(body["first_payment_date"]).date(), abs_operation_id=op["operation_id"],
                payment_schedule=body["schedule"],
            ))
        apply_transition(session, app, "T-42", actor, trigger=Trigger.LOAN_ISSUED, expected_version=version, changes={"issued_at": issued_at})
        emit(session, "LOAN_ISSUED", actor, application=app, payload={"product_code": app.final_product_code, "amount": str(app.final_amount), "term_months": app.final_term_months, "rate_percent": str(app.final_rate_percent), "abs_operation_id": op["operation_id"], "operation_type": operation})
        code = "NTF_LIMIT_OPENED" if operation == "CREDIT_LINE_LIMIT" else "NTF_LOAN_ISSUED"
        notify(session, app.client_user_id, code, application=app, amount=fmt_money(app.final_amount), account_masked=op["account_number_masked"], first_payment_date=fmt_date(op["first_payment_date"]))


HANDLERS = {
    JobKind.COMPLETENESS_CHECK: completeness_check,
    JobKind.ENRICH: enrich,
    JobKind.SCORE: score,
    JobKind.DECIDE: decide,
    JobKind.PREPARE_DOCUMENTS: prepare_documents,
    JobKind.ISSUE_LOAN: issue_loan,
}


def fail_after_exhausted(session: Session, job: dict[str, Any], actor: Actor) -> None:
    """A task kept failing with an unexpected error: hand the application to people (PROCESSING_ERROR)."""
    app = session.get(Application, job["application_id"])
    if app is None or app.status != job["expected_status"]:
        return
    stage_version = job.get("payload", {}).get("_stage_version")
    if stage_version is not None and app.version != stage_version:
        return
    fail_stage(session, app, actor, "UNEXPECTED")
