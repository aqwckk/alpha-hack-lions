"""Employee API: queue with tabs and SLA, full card, decisions, four eyes, retry, comments, AI summary."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, Header, Query
from fastapi.responses import JSONResponse, Response
from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..domain.configs import get_registry
from ..domain.dictionaries import (
    DOCUMENT_TYPES,
    EXTRA_REASON_CODES,
    FIELD_LABELS,
    INFO_REQUEST_FIELDS,
    MANUAL_DECLINE_CODES,
    UNDERWRITER_INFO_CODES,
)
from ..enums import ActorType, Command, Status
from ..errors import Conflict, Forbidden, NotFound
from ..models import Application, Decision, Document, DocumentContent
from ..schemas import (
    AddCommentRequest,
    AiSummaryResponse,
    CommentCommand,
    CounterOfferRequest,
    DeclineRequest,
    ErrorResponse,
    RequestInfoRequest,
    StaffCard,
    StaffPage,
    VersionOnly,
)
from ..services import ai, idempotency
from ..services import staff_commands as cmd
from ..services.access import load_for_staff, underwriter_scope
from ..services.core import Actor, audit, emit
from ..services.views import staff_application_view, staff_list_item, user_names
from .deps import risk_actor, staff_actor, underwriter_actor

router = APIRouter(prefix="/api/v1/bank", tags=["bank employees"])
ERRORS = {401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}, 404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}, 422: {"model": ErrorResponse}}
Tab = Literal["queue", "mine", "errors", "decided", "approval", "all"]


def _tab_filter(stmt: Select, tab: Tab, actor: Actor) -> Select:
    if tab == "queue":
        return stmt.where(Application.status == Status.MANUAL_REVIEW.value)
    if tab == "mine":
        return stmt.where(Application.status.in_([Status.IN_REVIEW.value, Status.PENDING_RISK_APPROVAL.value]), Application.assignee_id == actor.user_id)
    if tab == "errors":
        return stmt.where(Application.status == Status.PROCESSING_ERROR.value)
    if tab == "decided":
        mine = select(Decision.application_id).where(or_(Decision.decided_by == actor.user_id, Decision.proposed_by == actor.user_id), Decision.outcome.in_(["APPROVED", "COUNTER_OFFER", "DECLINED"]))
        return stmt.where(Application.id.in_(mine))
    if tab == "approval":
        if actor.type != ActorType.RISK_MANAGER:
            raise Forbidden(code="ROLE_NOT_ALLOWED")
        return stmt.where(Application.status == Status.PENDING_RISK_APPROVAL.value)
    if actor.type != ActorType.RISK_MANAGER:
        raise Forbidden("Список всех заявок доступен риск-менеджеру", code="ROLE_NOT_ALLOWED")
    return stmt


@router.get("/applications", response_model=StaffPage)
def list_applications(
    tab: Tab = Query("queue"),
    status: str | None = Query(default=None, description="Internal status filter (comma separated)"),
    product_code: str | None = None,
    outcome: str | None = Query(default=None, description="Outcome of the final decision"),
    mode: Literal["AUTO", "MANUAL"] | None = None,
    number: str | None = Query(default=None, max_length=16),
    inn: str | None = Query(default=None, max_length=12),
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    include_history: bool = True,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    actor: Actor = Depends(staff_actor),
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    """Tabs: queue (MANUAL_REVIEW, by SLA), mine, errors (PROCESSING_ERROR), decided (by me), approval and all (risk manager). Drafts are never shown."""
    stmt = select(Application).where(Application.status != Status.DRAFT.value)
    if actor.type == ActorType.UNDERWRITER:
        stmt = stmt.where(underwriter_scope(actor))
    stmt = _tab_filter(stmt, tab, actor)
    if status:
        stmt = stmt.where(Application.status.in_([s.strip() for s in status.split(",")]))
    if product_code:
        stmt = stmt.where(Application.product_code == product_code)
    if number:
        stmt = stmt.where(Application.application_number == number.strip().upper())
    if inn:
        stmt = stmt.where(Application.applicant_inn == inn.strip())
    if created_from:
        stmt = stmt.where(Application.created_at >= created_from)
    if created_to:
        stmt = stmt.where(Application.created_at < created_to)
    if not include_history:
        stmt = stmt.where(Application.is_history.is_(False))
    if outcome or mode:
        d = select(Decision.application_id).where(Decision.status == "FINAL", Decision.outcome.in_(["APPROVED", "COUNTER_OFFER", "DECLINED"]))
        if outcome:
            d = d.where(Decision.outcome == outcome)
        if mode:
            d = d.where(Decision.mode == mode)
        stmt = stmt.where(Application.id.in_(d))
    total = session.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    order = (Application.review_due_at.asc().nulls_last(), Application.updated_at.desc()) if tab in ("queue", "mine", "approval") else (Application.updated_at.desc(),)
    apps = list(session.execute(stmt.order_by(*order).offset((page - 1) * page_size).limit(page_size)).scalars())
    names = user_names(session, {a.assignee_id for a in apps})
    counters = {}
    base = select(func.count()).select_from(Application)
    counters["queue"] = session.execute(base.where(Application.status == Status.MANUAL_REVIEW.value)).scalar_one()
    counters["errors"] = session.execute(base.where(Application.status == Status.PROCESSING_ERROR.value)).scalar_one()
    counters["mine"] = session.execute(base.where(Application.status.in_([Status.IN_REVIEW.value, Status.PENDING_RISK_APPROVAL.value]), Application.assignee_id == actor.user_id)).scalar_one()
    if actor.type == ActorType.RISK_MANAGER:
        counters["approval"] = session.execute(base.where(Application.status == Status.PENDING_RISK_APPROVAL.value)).scalar_one()
    # reason texts need the values of the latest automatic decision (one batched query for the page)
    details: dict[Any, dict[str, Any]] = {}
    with_reasons = [a.id for a in apps if a.manual_review_reasons]
    if with_reasons:
        rows = session.execute(select(Decision.application_id, Decision.reason_details).where(Decision.application_id.in_(with_reasons), Decision.mode == "AUTO").order_by(Decision.created_at))
        for app_id, reason_details in rows:
            details[app_id] = reason_details or {}
    return {"items": [staff_list_item(session, a, names, details.get(a.id)) for a in apps], "page": page, "page_size": page_size, "total": total, "counters": counters}


@router.get("/applications/{application_id}", response_model=StaffCard, responses=ERRORS)
def card(application_id: uuid.UUID, view_context: Literal["QUEUE", "SEARCH", "ERROR_LIST"] = Query("QUEUE"), actor: Actor = Depends(staff_actor), session: Session = Depends(get_db)) -> dict[str, Any]:
    """Full card: form, registry data, sources with attempts, scoring by factors, policy rules path, decisions, history, audit.
    Each opening is written to the access journal (APPLICATION_VIEWED)."""
    app = load_for_staff(session, actor, application_id)
    emit(session, "APPLICATION_VIEWED", actor, application=app, payload={"view_context": view_context})
    audit(session, actor, "VIEW_APPLICATION", application_id=app.id, object_type="application", object_id=str(app.id), details={"view_context": view_context})
    session.commit()
    return staff_application_view(session, app, actor)


@router.get("/applications/{application_id}/documents/{document_id}/content", responses=ERRORS)
def download(application_id: uuid.UUID, document_id: uuid.UUID, actor: Actor = Depends(staff_actor), session: Session = Depends(get_db)) -> Response:
    app = load_for_staff(session, actor, application_id)
    doc = session.execute(select(Document).where(Document.id == document_id, Document.application_id == app.id, Document.deleted_at.is_(None))).scalar_one_or_none()
    if doc is None:
        raise NotFound("Документ не найден", code="DOCUMENT_NOT_FOUND")
    emit(session, "DOCUMENT_DOWNLOADED", actor, application=app, payload={"document_id": str(doc.id), "document_type": doc.document_type})
    audit(session, actor, "DOWNLOAD_DOCUMENT", application_id=app.id, object_type="document", object_id=str(doc.id))
    session.commit()
    content = session.get(DocumentContent, doc.storage_key).content
    return Response(content=content, media_type=doc.mime_type, headers={"Content-Disposition": f'attachment; filename="document-{doc.id}"', "Cache-Control": "no-store"})


def _command(application_id: uuid.UUID, actor: Actor, session: Session, key: str | None, name: str, payload: dict[str, Any], action) -> JSONResponse:
    def fn():
        app = load_for_staff(session, actor, application_id)
        action(app)
        session.flush()
        return 200, StaffCard.model_validate(staff_application_view(session, app, actor)).model_dump(mode="json")

    status, body, replayed = idempotency.run(session, actor, key, f"{name}:{application_id}", payload, fn)
    return JSONResponse(status_code=status, content=body, headers={"Idempotent-Replayed": "true"} if replayed else {})


def _already_taken(session: Session, actor: Actor, application_id: uuid.UUID) -> None:
    """The loser of a TAKE race no longer sees the application in its scope: answer 409 with the winner's name."""
    try:
        load_for_staff(session, actor, application_id)
    except NotFound:
        app = session.get(Application, application_id)
        if app is not None and app.status in (Status.IN_REVIEW.value, Status.PENDING_RISK_APPROVAL.value) and app.assignee_id and app.assignee_id != actor.user_id:
            name = user_names(session, {app.assignee_id}).get(app.assignee_id)
            raise Conflict(f"Заявку уже взял {name}", code="ALREADY_TAKEN", details={"assignee": name}) from None
        raise


@router.post("/applications/{application_id}/take", response_model=StaffCard, responses=ERRORS)
def take(application_id: uuid.UUID, body: VersionOnly, actor: Actor = Depends(underwriter_actor), session: Session = Depends(get_db), idempotency_key: str | None = Header(default=None)):
    """TAKE (T-25). Of two simultaneous takes one wins, the other gets 409 ALREADY_TAKEN."""
    _already_taken(session, actor, application_id)
    return _command(application_id, actor, session, idempotency_key, "TAKE", body.model_dump(), lambda app: cmd.take(session, actor, app, expected_version=body.expected_version))


@router.post("/applications/{application_id}/release", response_model=StaffCard, responses=ERRORS)
def release(application_id: uuid.UUID, body: CommentCommand, actor: Actor = Depends(underwriter_actor), session: Session = Depends(get_db), idempotency_key: str | None = Header(default=None)):
    """RELEASE (T-26), assignee only, comment required."""
    return _command(application_id, actor, session, idempotency_key, "RELEASE", body.model_dump(), lambda app: cmd.release(session, actor, app, expected_version=body.expected_version, comment=body.comment))


@router.post("/applications/{application_id}/approve", response_model=StaffCard, responses=ERRORS)
def approve(application_id: uuid.UUID, body: CommentCommand, actor: Actor = Depends(underwriter_actor), session: Session = Depends(get_db), idempotency_key: str | None = Header(default=None)):
    """APPROVE on the requested terms (T-27, or T-28 when four eyes are required: above authority limit or override)."""
    return _command(application_id, actor, session, idempotency_key, "APPROVE", body.model_dump(), lambda app: cmd.decide_positive(session, actor, app, command=Command.APPROVE, expected_version=body.expected_version, comment=body.comment, options=None))


@router.post("/applications/{application_id}/counter-offer", response_model=StaffCard, responses=ERRORS)
def counter_offer(application_id: uuid.UUID, body: CounterOfferRequest, actor: Actor = Depends(underwriter_actor), session: Session = Depends(get_db), idempotency_key: str | None = Header(default=None)):
    """MAKE_COUNTER_OFFER: 1-3 options (original product or CREDIT_LINE) within product bounds; rate from the grade matrix."""
    options = [o.model_dump(mode="json") for o in body.options]
    return _command(application_id, actor, session, idempotency_key, "MAKE_COUNTER_OFFER", body.model_dump(mode="json"), lambda app: cmd.decide_positive(session, actor, app, command=Command.MAKE_COUNTER_OFFER, expected_version=body.expected_version, comment=body.comment, options=options))


@router.post("/applications/{application_id}/request-info", response_model=StaffCard, responses=ERRORS)
def request_info(application_id: uuid.UUID, body: RequestInfoRequest, actor: Actor = Depends(underwriter_actor), session: Session = Depends(get_db), idempotency_key: str | None = Header(default=None)):
    """REQUEST_INFO (T-29): 1-10 structured items with NI_* codes; the application stays pinned to the underwriter."""
    items = [i.model_dump() for i in body.items]
    return _command(application_id, actor, session, idempotency_key, "REQUEST_INFO", body.model_dump(), lambda app: cmd.request_info(session, actor, app, expected_version=body.expected_version, items=items, comment=body.comment))


@router.post("/applications/{application_id}/decline", response_model=StaffCard, responses=ERRORS)
def decline(application_id: uuid.UUID, body: DeclineRequest, actor: Actor = Depends(underwriter_actor), session: Session = Depends(get_db), idempotency_key: str | None = Header(default=None)):
    """DECLINE (T-30): reason codes SF_*/DCL_* (except DCL_AFFORDABILITY) and a comment are required."""
    return _command(application_id, actor, session, idempotency_key, "DECLINE", body.model_dump(), lambda app: cmd.decline(session, actor, app, expected_version=body.expected_version, reason_codes=body.reason_codes, comment=body.comment))


@router.post("/applications/{application_id}/confirm", response_model=StaffCard, responses=ERRORS)
def confirm(application_id: uuid.UUID, body: CommentCommand, actor: Actor = Depends(risk_actor), session: Session = Depends(get_db), idempotency_key: str | None = Header(default=None)):
    """CONFIRM_DECISION (T-31), risk manager who is not the author of the draft decision."""
    return _command(application_id, actor, session, idempotency_key, "CONFIRM_DECISION", body.model_dump(), lambda app: cmd.confirm_decision(session, actor, app, expected_version=body.expected_version, comment=body.comment))


@router.post("/applications/{application_id}/return", response_model=StaffCard, responses=ERRORS)
def return_decision(application_id: uuid.UUID, body: CommentCommand, actor: Actor = Depends(risk_actor), session: Session = Depends(get_db), idempotency_key: str | None = Header(default=None)):
    """RETURN_DECISION (T-32) to the same underwriter, comment required."""
    return _command(application_id, actor, session, idempotency_key, "RETURN_DECISION", body.model_dump(), lambda app: cmd.return_decision(session, actor, app, expected_version=body.expected_version, comment=body.comment))


@router.post("/applications/{application_id}/retry", response_model=StaffCard, responses=ERRORS)
def retry(application_id: uuid.UUID, body: VersionOnly, actor: Actor = Depends(staff_actor), session: Session = Depends(get_db), idempotency_key: str | None = Header(default=None)):
    """RETRY_PROCESSING (T-44): back to failed_stage, retry counters reset, the stage task is queued again."""
    return _command(application_id, actor, session, idempotency_key, "RETRY_PROCESSING", body.model_dump(), lambda app: cmd.retry_processing(session, actor, app, expected_version=body.expected_version))


@router.post("/applications/{application_id}/comments", status_code=201, responses=ERRORS)
def add_comment(application_id: uuid.UUID, body: AddCommentRequest, actor: Actor = Depends(staff_actor), session: Session = Depends(get_db)) -> dict[str, Any]:
    """Internal comment, never visible to the client."""
    app = load_for_staff(session, actor, application_id)
    c = cmd.add_comment(session, actor, app, body.body)
    session.commit()
    return {"id": str(c.id), "created_at": c.created_at.isoformat()}


@router.post("/applications/{application_id}/ai-summary", response_model=AiSummaryResponse, responses=ERRORS)
def ai_summary(application_id: uuid.UUID, actor: Actor = Depends(staff_actor), session: Session = Depends(get_db)) -> dict[str, Any]:
    """Optional summary for the underwriter (template by default, local open-weight model with OLLAMA_URL)."""
    app = load_for_staff(session, actor, application_id)
    result = ai.underwriter_summary(staff_application_view(session, app, actor))
    emit(session, "AI_SUMMARY_GENERATED", actor, application=app, payload={"model_name": result["model_name"], "latency_ms": result["latency_ms"], "fallback_used": result["fallback_used"]})
    session.commit()
    return result


@router.get("/dictionaries")
def dictionaries(actor: Actor = Depends(staff_actor)) -> dict[str, Any]:
    """Codes and templates for decision dialogs: decline reasons, NI_* items, requestable fields, document types."""
    reasons = {**get_registry().policy_content()["reason_codes"], **EXTRA_REASON_CODES}
    return {
        "decline_reason_codes": [{"code": c, "employee_text": reasons[c]["employee_text"], "client_text": reasons[c]["client_text"]} for c in MANUAL_DECLINE_CODES],
        "info_reason_codes": [{"code": c, "client_text_template": reasons[c]["client_text"], "employee_text": reasons[c]["employee_text"]} for c in UNDERWRITER_INFO_CODES],
        "requestable_fields": [{"field_name": f, "label": FIELD_LABELS[f]} for f in INFO_REQUEST_FIELDS],
        "document_types": [{"code": k, **v} for k, v in DOCUMENT_TYPES.items()],
    }

