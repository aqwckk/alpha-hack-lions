"""Client API: own applications only (foreign ones answer 404), client_status instead of internal codes."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, File, Form, Header, Query, Request, UploadFile
from fastapi.responses import JSONResponse, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..domain.dictionaries import today_msk
from ..domain.money import add_months, payment_schedule, totals
from ..errors import NotFound, ValidationFailed
from ..models import (
    Application,
    Document,
    DocumentContent,
    DocumentPackage,
    GeneratedDocument,
    OfferOption,
)
from ..schemas import (
    AcceptOfferRequest,
    ClientApplication,
    ClientApplicationListItem,
    ClientApplicationPage,
    CreateApplicationRequest,
    DeclineOfferRequest,
    DraftResponse,
    DraftUpdateRequest,
    ErrorResponse,
    ExplanationResponse,
    OptionalVersion,
    PrefillRequest,
    PrefillResponse,
    RespondInfoRequest,
    ScheduleResponse,
    SigningCodeResponse,
    SignRequest,
    VersionOnly,
)
from ..services import ai, idempotency
from ..services import client_commands as cmd
from ..services.access import client_scope, load_for_client
from ..services.core import Actor
from ..services.views import client_application_view, client_list_item
from ..services.schedules import package_schedule
from .deps import client_actor

router = APIRouter(prefix="/api/v1/applications", tags=["client applications"])
ERRORS = {401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}, 404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}, 422: {"model": ErrorResponse}}


def view_json(session: Session, app: Application, actor: Actor) -> dict[str, Any]:
    """Client view validated against the strict allowlist schema (no internal fields can leak)."""
    return ClientApplication.model_validate(client_application_view(session, app, actor)).model_dump(mode="json")


def respond(status: int, body: dict[str, Any], replayed: bool) -> JSONResponse:
    headers = {"Idempotent-Replayed": "true"} if replayed else {}
    return JSONResponse(status_code=status, content=body, headers=headers)


@router.get("", response_model=ClientApplicationPage)
def list_applications(page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100), actor: Actor = Depends(client_actor), session: Session = Depends(get_db)) -> dict[str, Any]:
    scope = client_scope(actor)
    total = session.execute(select(func.count()).select_from(Application).where(scope)).scalar_one()
    apps = session.execute(select(Application).where(scope).order_by(Application.updated_at.desc(), Application.id.desc()).offset((page - 1) * page_size).limit(page_size)).scalars()
    return {"items": [ClientApplicationListItem.model_validate(client_list_item(session, a)).model_dump() for a in apps], "page": page, "page_size": page_size, "total": total}


@router.post("", status_code=201, response_model=ClientApplication, responses=ERRORS)
def create(body: CreateApplicationRequest, actor: Actor = Depends(client_actor), session: Session = Depends(get_db), idempotency_key: str | None = Header(default=None)):
    """CREATE_APPLICATION (T-01) from the selection wizard. Requires Idempotency-Key."""
    def fn():
        app = cmd.create_application(session, actor, product_code=body.product_code, purpose=body.purpose, amount=body.amount, term_months=body.term_months, wizard_session_id=body.wizard_session_id)
        session.flush()
        return 201, view_json(session, app, actor)

    return respond(*idempotency.run(session, actor, idempotency_key, "CREATE_APPLICATION", body.model_dump(mode="json"), fn))


@router.get("/{application_id}", response_model=ClientApplication, responses=ERRORS)
def get_application(application_id: uuid.UUID, actor: Actor = Depends(client_actor), session: Session = Depends(get_db)) -> dict[str, Any]:
    """Application with client_status, texts, progress, available_actions, offer, signing, notifications. Poll every 3-15 s."""
    return view_json(session, load_for_client(session, actor, application_id), actor)


@router.patch("/{application_id}", response_model=DraftResponse, responses=ERRORS)
def update_draft(application_id: uuid.UUID, body: DraftUpdateRequest, actor: Actor = Depends(client_actor), session: Session = Depends(get_db), idempotency_key: str | None = Header(default=None)):
    """UPDATE_DRAFT (autosave). Only the fields present in the body change (null clears a field).

    Valid fields are saved even if others fail the format check; those come back in field_errors.
    """
    parsed = body
    fields = {k: getattr(parsed, k) for k in parsed.model_fields_set if k != "expected_version"}
    app = load_for_client(session, actor, application_id)

    def fn():
        _, errors = cmd.update_draft(session, actor, app, expected_version=parsed.expected_version, fields=fields)
        return 200, {"application": view_json(session, app, actor), "field_errors": errors}

    return respond(*idempotency.run(session, actor, idempotency_key, f"UPDATE_DRAFT:{application_id}", body.model_dump(mode="json", exclude_unset=True), fn, required=False))


@router.post("/{application_id}/prefill", response_model=PrefillResponse, responses=ERRORS)
def prefill(application_id: uuid.UUID, body: PrefillRequest, actor: Actor = Depends(client_actor), session: Session = Depends(get_db)):
    """PREFILL_BY_INN: data from REGISTRY and FNS mocks, early warnings (business age, status, unreliable data)."""
    app = load_for_client(session, actor, application_id)
    result = cmd.prefill(session, actor, app, expected_version=body.expected_version, inn=body.inn)
    session.commit()
    return {"prefill": result, "application": view_json(session, app, actor)}


@router.put("/{application_id}/consents/{consent_type}", response_model=ClientApplication, responses=ERRORS)
def give_consent(application_id: uuid.UUID, consent_type: str, body: OptionalVersion | None = None, actor: Actor = Depends(client_actor), session: Session = Depends(get_db)):
    """GIVE_CONSENT: server time, text version and hash, IP and user agent are recorded."""
    app = load_for_client(session, actor, application_id)
    cmd.give_consent(session, actor, app, consent_type, expected_version=body.expected_version if body else None)
    session.commit()
    return view_json(session, app, actor)


@router.delete("/{application_id}/consents/{consent_type}", response_model=ClientApplication, responses=ERRORS)
def revoke_consent(application_id: uuid.UUID, consent_type: str, expected_version: int | None = Query(default=None), actor: Actor = Depends(client_actor), session: Session = Depends(get_db)):
    app = load_for_client(session, actor, application_id)
    cmd.revoke_consent(session, actor, app, consent_type, expected_version=expected_version)
    session.commit()
    return view_json(session, app, actor)


@router.post("/{application_id}/documents", status_code=201, response_model=ClientApplication, responses=ERRORS)
async def upload_document(
    application_id: uuid.UUID,
    request: Request,
    document_type: str = Form(...),
    file: UploadFile = File(...),
    info_request_item_id: uuid.UUID | None = Form(default=None),
    expected_version: int | None = Form(default=None),
    actor: Actor = Depends(client_actor),
    session: Session = Depends(get_db),
):
    """UPLOAD_DOCUMENT: PDF, JPG or PNG by signature, up to 10 MB; 20 draft files and a separate quota of 20 per information-request item."""
    limit = get_settings().max_document_bytes
    content = await file.read(limit + 1)
    if len(content) > limit:
        raise ValidationFailed(fields=[{"field": "file", "code": "DOCUMENT_TOO_LARGE", "message": "Файл больше 10 МБ. Сожмите его или разделите на части"}], code="DOCUMENT_TOO_LARGE")

    def work():
        app = load_for_client(session, actor, application_id)
        cmd.upload_document(session, actor, app, document_type=document_type, file_name=file.filename or "document", content=content, info_request_item_id=info_request_item_id, expected_version=expected_version)
        session.commit()
        return view_json(session, app, actor)

    from starlette.concurrency import run_in_threadpool

    return JSONResponse(status_code=201, content=await run_in_threadpool(work))


@router.get("/{application_id}/documents/{document_id}/content", responses=ERRORS)
def download_document(application_id: uuid.UUID, document_id: uuid.UUID, actor: Actor = Depends(client_actor), session: Session = Depends(get_db)) -> Response:
    app = load_for_client(session, actor, application_id)
    doc = session.execute(select(Document).where(Document.id == document_id, Document.application_id == app.id, Document.deleted_at.is_(None))).scalar_one_or_none()
    if doc is None:
        raise NotFound("Документ не найден", code="DOCUMENT_NOT_FOUND")
    content = session.get(DocumentContent, doc.storage_key).content
    return Response(content=content, media_type=doc.mime_type, headers={"Content-Disposition": f'attachment; filename="document-{doc.id}"', "Cache-Control": "no-store"})


@router.delete("/{application_id}/documents/{document_id}", response_model=ClientApplication, responses=ERRORS)
def delete_document(application_id: uuid.UUID, document_id: uuid.UUID, expected_version: int | None = Query(default=None), actor: Actor = Depends(client_actor), session: Session = Depends(get_db)):
    app = load_for_client(session, actor, application_id)
    cmd.delete_document(session, actor, app, document_id, expected_version=expected_version)
    session.commit()
    return view_json(session, app, actor)


def _command(application_id: uuid.UUID, actor: Actor, session: Session, key: str | None, name: str, payload: dict[str, Any], action) -> JSONResponse:
    def fn():
        app = load_for_client(session, actor, application_id)
        action(app)
        session.flush()
        return 200, view_json(session, app, actor)

    return respond(*idempotency.run(session, actor, key, f"{name}:{application_id}", payload, fn))


@router.post("/{application_id}/submit", response_model=ClientApplication, responses=ERRORS)
def submit(application_id: uuid.UUID, body: VersionOnly, actor: Actor = Depends(client_actor), session: Session = Depends(get_db), idempotency_key: str | None = Header(default=None)):
    """SUBMIT (T-03): full validation, three consents, duplicate check. Requires Idempotency-Key."""
    return _command(application_id, actor, session, idempotency_key, "SUBMIT", body.model_dump(), lambda app: cmd.submit(session, actor, app, expected_version=body.expected_version))


@router.post("/{application_id}/info-response", response_model=ClientApplication, responses=ERRORS)
def respond_info(application_id: uuid.UUID, body: RespondInfoRequest, actor: Actor = Depends(client_actor), session: Session = Depends(get_db), idempotency_key: str | None = Header(default=None)):
    """RESPOND_INFO (T-10): answers to all required items; FIELD answers change the form with history."""
    answers = [a.model_dump(mode="json") for a in body.answers]
    return _command(application_id, actor, session, idempotency_key, "RESPOND_INFO", body.model_dump(mode="json"), lambda app: cmd.respond_info(session, actor, app, expected_version=body.expected_version, answers=answers))


@router.post("/{application_id}/withdraw", response_model=ClientApplication, responses=ERRORS)
def withdraw(application_id: uuid.UUID, body: VersionOnly, actor: Actor = Depends(client_actor), session: Session = Depends(get_db), idempotency_key: str | None = Header(default=None)):
    """WITHDRAW (T-04, T-11, T-41, T-45)."""
    return _command(application_id, actor, session, idempotency_key, "WITHDRAW", body.model_dump(), lambda app: cmd.withdraw(session, actor, app, expected_version=body.expected_version))


@router.post("/{application_id}/offer/accept", response_model=ClientApplication, responses=ERRORS)
def accept_offer(application_id: uuid.UUID, body: AcceptOfferRequest, actor: Actor = Depends(client_actor), session: Session = Depends(get_db), idempotency_key: str | None = Header(default=None)):
    """ACCEPT_OFFER (T-33): the chosen option becomes the final terms; 409 OFFER_EXPIRED after expires_at."""
    return _command(application_id, actor, session, idempotency_key, "ACCEPT_OFFER", body.model_dump(mode="json"), lambda app: cmd.accept_offer(session, actor, app, expected_version=body.expected_version, option_id=body.option_id))


@router.post("/{application_id}/offer/decline", response_model=ClientApplication, responses=ERRORS)
def decline_offer(application_id: uuid.UUID, body: DeclineOfferRequest, actor: Actor = Depends(client_actor), session: Session = Depends(get_db), idempotency_key: str | None = Header(default=None)):
    """DECLINE_OFFER (T-34, T-38, T-46) with an optional OD_* reason."""
    return _command(application_id, actor, session, idempotency_key, "DECLINE_OFFER", body.model_dump(), lambda app: cmd.decline_offer(session, actor, app, expected_version=body.expected_version, reason_code=body.reason_code))


@router.post("/{application_id}/signing-code", response_model=SigningCodeResponse, responses=ERRORS)
def signing_code(application_id: uuid.UUID, actor: Actor = Depends(client_actor), session: Session = Depends(get_db), idempotency_key: str | None = Header(default=None)):
    """REQUEST_SIGNING_CODE: 6 digits, TTL 5 min, previous code revoked, at most 5 per hour. Shown in the product, never sent outside."""
    def fn():
        app = load_for_client(session, actor, application_id)
        return 200, cmd.request_signing_code(session, actor, app)

    return respond(*idempotency.run(session, actor, idempotency_key, f"REQUEST_SIGNING_CODE:{application_id}", {}, fn))


@router.post("/{application_id}/sign", response_model=ClientApplication, responses=ERRORS)
def sign(application_id: uuid.UUID, body: SignRequest, actor: Actor = Depends(client_actor), session: Session = Depends(get_db), idempotency_key: str | None = Header(default=None)):
    """SIGN (T-39): valid code bound to the document hashes; a repeated key returns the first result (one loan)."""
    return _command(application_id, actor, session, idempotency_key, "SIGN", body.model_dump(), lambda app: cmd.sign(session, actor, app, expected_version=body.expected_version, code=body.code.strip()))


@router.get("/{application_id}/signing-documents/{document_id}", responses=ERRORS)
def signing_document(application_id: uuid.UUID, document_id: uuid.UUID, actor: Actor = Depends(client_actor), session: Session = Depends(get_db)) -> Response:
    """Text of a generated document (EDO mock) for reading before signing."""
    app = load_for_client(session, actor, application_id)
    doc = session.execute(
        select(GeneratedDocument).join(DocumentPackage, DocumentPackage.id == GeneratedDocument.package_id).where(GeneratedDocument.id == document_id, DocumentPackage.application_id == app.id)
    ).scalar_one_or_none()
    if doc is None:
        raise NotFound("Документ не найден", code="DOCUMENT_NOT_FOUND")
    return Response(content=doc.content, media_type="text/plain; charset=utf-8", headers={"X-Document-Sha256": doc.sha256, "Cache-Control": "no-store"})


@router.get("/{application_id}/schedule", response_model=ScheduleResponse, responses=ERRORS)
def schedule(application_id: uuid.UUID, option_id: uuid.UUID | None = Query(default=None), actor: Actor = Depends(client_actor), session: Session = Depends(get_db)) -> dict[str, Any]:
    """Payment schedule of an offer option or of the issued loan (for a credit line: the full limit over the tranche term)."""
    app = load_for_client(session, actor, application_id)
    option_id = option_id or app.final_option_id
    option = session.get(OfferOption, option_id) if option_id else None
    if option is None or app.current_offer_id is None:
        raise NotFound("График недоступен", code="SCHEDULE_NOT_FOUND")
    from ..models import Offer

    offer = session.get(Offer, option.offer_id)
    if offer is None or offer.application_id != app.id:
        raise NotFound("График недоступен", code="SCHEDULE_NOT_FOUND")
    from ..models import Loan

    loan = session.execute(select(Loan).where(Loan.application_id == app.id)).scalar_one_or_none()
    first = loan.first_payment_date if loan and loan.product_code == option.product_code else add_months(today_msk(), 1)
    term = option.tranche_max_term_months or option.term_months
    rows = None
    if app.final_option_id == option.id:
        if loan is not None and loan.payment_schedule:
            rows = loan.payment_schedule
        else:
            package = session.execute(select(DocumentPackage).where(DocumentPackage.application_id == app.id, DocumentPackage.offer_option_id == option.id).order_by(DocumentPackage.created_at.desc()).limit(1)).scalar_one_or_none()
            if package is not None:
                rows = package_schedule(session, package)
        if rows:
            from datetime import date

            first = date.fromisoformat(rows[0]["date"])
    t = totals(option.amount, option.rate_percent, term)
    return {
        "product_code": option.product_code, "amount": str(option.amount), "term_months": term, "rate_percent": str(option.rate_percent),
        "monthly_payment": str(t["monthly_payment"]), "total_payment": str(t["total_payment"]), "overpayment": str(t["overpayment"]),
        "first_payment_date": first.isoformat(), "rows": rows if rows is not None else payment_schedule(option.amount, option.rate_percent, term, first),
    }


@router.post("/{application_id}/explain", response_model=ExplanationResponse, responses=ERRORS)
def explain(application_id: uuid.UUID, actor: Actor = Depends(client_actor), session: Session = Depends(get_db)) -> dict[str, Any]:
    """'Explain simpler' (optional AI with a deterministic template fallback; numbers are inserted after generation)."""
    app = load_for_client(session, actor, application_id)
    return ai.plain_explanation(client_application_view(session, app, actor))

