"""Client commands: draft, prefill, consents, documents, submit, answer, withdraw, offer, signing."""

from __future__ import annotations

import hashlib
import logging
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import session_scope
from ..domain.configs import get_registry
from ..domain.dictionaries import (
    CONSENT_TEXTS,
    DOCUMENT_TYPES,
    OFFER_DECLINE_REASONS,
    SIGNING_CODE_EXPIRED_TEXT,
    consent_text_sha256,
    today_msk,
)
from ..domain.inn import applicant_type_for, inn_error
from ..domain.money import add_months, months_between
from ..domain.validation import EDITABLE_FIELDS, field_error, normalize, submit_errors
from ..enums import Command, JobKind, Status
from ..errors import (
    Conflict,
    Forbidden,
    NotFound,
    ServiceUnavailable,
    TooManyRequests,
    ValidationFailed,
    invalid_transition,
)
from ..models import (
    Application,
    Company,
    CompanyMembership,
    Consent,
    Document,
    DocumentContent,
    DocumentPackage,
    FieldChange,
    GeneratedDocument,
    InfoRequest,
    InfoRequestItem,
    Job,
    Notification,
    Offer,
    OfferOption,
    Signature,
    SigningCode,
    SourceSnapshot,
)
from . import integrations
from .core import (
    Actor,
    apply_transition,
    audit,
    bump_version,
    emit,
    enqueue,
    notify,
    utcnow,
)
from .views import active_consents, client_reasons, consent_rows

log = logging.getLogger("app.client")

PREFILL_FIELDS = (
    "company_full_name", "company_short_name", "ogrn", "registration_date", "company_status", "okved_main_code", "okved_main_name",
    "legal_address_region", "director_full_name", "founders", "sme_category", "tax_regime", "employees_count",
)
MAGIC = {b"%PDF-": "application/pdf", b"\x89PNG\r\n\x1a\n": "image/png", b"\xff\xd8\xff": "image/jpeg"}
WITHDRAW_TRANSITIONS = {
    Status.DRAFT: "T-04",
    Status.INFO_REQUESTED: "T-11",
    Status.PROCESSING_ERROR: "T-45",
}
DECLINE_OFFER_TRANSITIONS = {Status.OFFER_PENDING: "T-34", Status.OFFER_ACCEPTED: "T-38", Status.SIGNING: "T-38", Status.PROCESSING_ERROR: "T-46"}


def _product(product_code: str) -> dict[str, Any]:
    return get_registry().policy_content()["products"][product_code]


def next_application_number(session: Session) -> str:
    n = session.execute(text("SELECT nextval('application_number_seq')")).scalar_one()
    return f"A-{n:06d}"


# ------------------------------------------------------------------------------ create / draft


def create_application(session: Session, actor: Actor, *, product_code: str, purpose: str, amount: Any, term_months: Any, wizard_session_id: str | None) -> Application:
    products = get_registry().policy_content()["products"]
    if product_code not in products:
        raise ValidationFailed(fields=[{"field": "product_code", "code": "INVALID_FORMAT", "message": "Неизвестный продукт"}])
    if not products[product_code]["direct_application"]:
        raise ValidationFailed("Этот продукт оформляется только как вариант предложения банка", code="PRODUCT_NOT_DIRECT")
    errors = []
    values: dict[str, Any] = {}
    for field, value in (("purpose", purpose), ("amount", amount), ("term_months", term_months)):
        v, err = normalize(field, value)
        if err:
            errors.append(err)
        values[field] = v
    if values.get("purpose") and values["purpose"] not in products[product_code]["allowed_purposes"]:
        errors.append(field_error("purpose", "PURPOSE_NOT_ALLOWED"))
    if errors:
        raise ValidationFailed(fields=errors)
    now = utcnow()
    app = Application(
        id=uuid.uuid4(),
        application_number=next_application_number(session),
        client_user_id=actor.user_id,
        status=Status.DRAFT.value,
        version=1,
        product_code=product_code,
        purpose=values["purpose"],
        amount=values["amount"],
        term_months=values["term_months"],
        representative_role=None,
        wizard_session_id=(wizard_session_id or None) and wizard_session_id[:64],
        created_at=now,
        updated_at=now,
        status_changed_at=now,
    )
    session.add(app)
    session.flush()
    from ..models import StatusHistory

    session.add(StatusHistory(application_id=app.id, from_status=None, to_status=Status.DRAFT.value, transition_id="T-01", trigger=Command.CREATE_APPLICATION.value, actor_type=actor.type.value, actor_id=actor.user_id, version=1, occurred_at=now))
    emit(session, "STATUS_CHANGED", actor, application=app, occurred_at=now, payload={"from_status": None, "to_status": "DRAFT", "transition_id": "T-01", "command": "CREATE_APPLICATION"})
    emit(session, "APPLICATION_CREATED", actor, application=app, occurred_at=now, payload={"product_code": product_code, "purpose": app.purpose, "amount": str(app.amount) if app.amount else None, "term_months": app.term_months, "wizard_session_id": app.wizard_session_id})
    audit(session, actor, Command.CREATE_APPLICATION.value, application_id=app.id, object_type="application", object_id=str(app.id))
    return app


def link_company(session: Session, actor: Actor, inn: str, representative_role: str | None) -> Company:
    """Client may act for an INN of their company or for a company nobody represents yet (A-44, A-11)."""
    company = session.execute(select(Company).where(Company.inn == inn)).scalar_one_or_none()
    if company is None:
        company = Company(id=uuid.uuid4(), inn=inn, applicant_type=applicant_type_for(inn))
        session.add(company)
        session.flush()
    members = list(session.execute(select(CompanyMembership.user_id).where(CompanyMembership.company_id == company.id)).scalars())
    if members and actor.user_id not in members:
        raise Forbidden("Эта компания закреплена за другим представителем. Обратитесь в банк", code="COMPANY_ACCESS_DENIED")
    if not members:
        session.add(CompanyMembership(id=uuid.uuid4(), user_id=actor.user_id, company_id=company.id, representative_role=representative_role))
    return company


def update_draft(session: Session, actor: Actor, app: Application, *, expected_version: int | None, fields: dict[str, Any]) -> tuple[Application, list[dict[str, Any]]]:
    if app.status != Status.DRAFT:
        raise invalid_transition(app.status, "FILLING", internal=False)
    unknown = [f for f in fields if f not in EDITABLE_FIELDS]
    if unknown:
        raise ValidationFailed(fields=[{"field": f, "code": "NOT_EDITABLE", "message": "Поле нельзя изменить"} for f in unknown])
    changes: dict[str, Any] = {}
    errors = []
    for field, raw in fields.items():
        value, err = normalize(field, raw)
        if err:
            errors.append(err)
            continue
        changes[field] = value
    if "applicant_inn" in changes and changes["applicant_inn"] != app.applicant_inn:
        inn = changes["applicant_inn"]
        if inn:
            company = link_company(session, actor, inn, changes.get("representative_role") or app.representative_role)
            changes.update(company_id=company.id, applicant_type=applicant_type_for(inn))
        else:
            changes.update(company_id=None, applicant_type=None)
        changes.update(inn_check_status="NOT_CHECKED", registry_data=None, company_short_name=None, prefilled_at=None, early_warnings=None)
    if changes:
        bump_version(session, app, actor, expected_version=expected_version, changes=changes, allowed_statuses=(Status.DRAFT,))
    return app, errors


def _early_warnings(product_code: str, registry: dict[str, Any], fns: dict[str, Any] | None) -> list[dict[str, Any]]:
    """H3: stop factors visible without the bureau consent (status, business age, unreliable data)."""
    pol = get_registry().policy_content()
    product = pol["products"][product_code]
    stop = pol["stop_factors"]
    codes: list[str] = []
    details: dict[str, Any] = {}
    if registry.get("company_status") in stop["blocked_company_statuses"]:
        codes.append("SF_COMPANY_STATUS")
    if registry.get("registration_date"):
        reg_date = date.fromisoformat(registry["registration_date"])
        age = months_between(reg_date, today_msk())
        if age < product["min_business_age_months"]:
            codes.append("SF_BUSINESS_AGE")
            details["SF_BUSINESS_AGE"] = {
                "min_business_age_months": product["min_business_age_months"],
                "registration_date": registry["registration_date"],
                "eligible_date": add_months(reg_date, product["min_business_age_months"]).isoformat(),
            }
    flags = [f for f in ((fns or {}).get("unreliable_flags") or []) if f in stop["unreliable_flags"]]
    if flags:
        codes.append("SF_UNRELIABLE_REGISTRY_DATA")
    out = []
    for code, reason in zip(codes, [client_reasons([c], details)[0] for c in codes], strict=True):
        out.append({"reason_code": code, "text": f"Скорее всего, банк откажет: {reason['text']}", "next_step": reason["next_step"]})
    return out


def _save_snapshot(session: Session, app: Application, res: integrations.SourceResult, *, stage: str, attempt: int, inn: str) -> SourceSnapshot:
    s = get_settings()
    snap = SourceSnapshot(
        id=uuid.uuid4(),
        application_id=app.id,
        source=res.source,
        stage=stage,
        inn=inn,
        attempt=attempt,
        outcome=res.outcome,
        error_code=res.error_code,
        http_status=res.http_status,
        external_request_id=res.external_request_id,
        requested_at=res.requested_at,
        responded_at=res.responded_at,
        duration_ms=res.duration_ms,
        response=res.data,
        valid_until=res.responded_at + timedelta(seconds=s.source_cache_ttl_seconds) if res.ok else None,
    )
    session.add(snap)
    return snap


def prefill(session: Session, actor: Actor, app: Application, *, expected_version: int | None, inn: str | None) -> dict[str, Any]:
    if app.status != Status.DRAFT:
        raise invalid_transition(app.status, "FILLING", internal=False)
    if inn is not None:
        _, errors = update_draft(session, actor, app, expected_version=expected_version, fields={"applicant_inn": inn})
        if errors:
            raise ValidationFailed(fields=errors)
        expected_version = app.version
    if not app.applicant_inn:
        raise ValidationFailed(fields=[field_error("applicant_inn", "REQUIRED")])
    inn = app.applicant_inn
    s = get_settings()
    started = utcnow()
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = {src: pool.submit(integrations.fetch_source, src, inn, timeout=s.prefill_timeout_seconds, correlation_id=actor.correlation_id) for src in ("REGISTRY", "FNS")}
        results = {src: f.result() for src, f in futures.items()}
    for res in results.values():
        _save_snapshot(session, app, res, stage="PREFILL", attempt=1, inn=inn)
    latency = int((utcnow() - started).total_seconds() * 1000)
    reg, fns = results["REGISTRY"], results["FNS"]
    changes: dict[str, Any] = {"prefilled_at": utcnow()}
    if reg.outcome == "SUCCESS" and reg.data.get("found"):
        data = {k: reg.data.get(k) for k in PREFILL_FIELDS}
        if fns.outcome == "SUCCESS":
            data.update({k: fns.data.get(k) for k in ("sme_category", "tax_regime", "employees_count")})
        warnings = _early_warnings(app.product_code, reg.data, fns.data if fns.ok else None)
        changes.update(inn_check_status="FOUND", registry_data=data, company_short_name=reg.data.get("company_short_name"), applicant_type=reg.data.get("applicant_type") or applicant_type_for(inn), early_warnings=warnings)
        result = {"status": "FOUND", "message": None}
        prefilled = sum(1 for k in PREFILL_FIELDS if data.get(k) not in (None, [], "")) + 1
        emit(session, "PREFILL_COMPLETED", actor, application=app, payload={"applicant_type": changes["applicant_type"], "fields_prefilled": prefilled, "fields_total": len(PREFILL_FIELDS) + 1, "sources": [k for k, r in results.items() if r.outcome == "SUCCESS"], "latency_ms": latency})
        if warnings:
            emit(session, "EARLY_CHECK_WARNING_SHOWN", actor, application=app, payload={"product_code": app.product_code, "reason_codes": [w["reason_code"] for w in warnings]})
        company = session.get(Company, app.company_id) if app.company_id else None
        if company is not None and not company.short_name:
            company.short_name = changes["company_short_name"]
    elif reg.outcome == "SUCCESS":
        changes.update(inn_check_status="NOT_FOUND", registry_data=None, company_short_name=None, early_warnings=None)
        result = {"status": "NOT_FOUND", "message": field_error("applicant_inn", "INN_NOT_FOUND")["message"]}
        emit(session, "PREFILL_FAILED", actor, application=app, payload={"reason": "NOT_FOUND"})
    else:
        changes.update(inn_check_status="UNAVAILABLE")
        result = {"status": "SOURCE_UNAVAILABLE", "message": "Не удалось получить сведения, попробуем при обработке заявки. Можно продолжать"}
        emit(session, "PREFILL_FAILED", actor, application=app, payload={"reason": "SOURCE_UNAVAILABLE"})
    bump_version(session, app, actor, expected_version=expected_version, changes=changes, allowed_statuses=(Status.DRAFT,))
    audit(session, actor, Command.PREFILL_BY_INN.value, application_id=app.id, object_type="application", object_id=str(app.id), details={"result": result["status"]})
    return result


# ------------------------------------------------------------------------------ consents and documents


def give_consent(session: Session, actor: Actor, app: Application, consent_type: str, *, expected_version: int | None) -> Consent:
    if consent_type not in CONSENT_TEXTS:
        raise NotFound("Неизвестный тип согласия", code="UNKNOWN_CONSENT")
    if app.status != Status.DRAFT:
        raise invalid_transition(app.status, None, internal=False)
    now = utcnow()
    existing = active_consents(consent_rows(session, app), now).get(consent_type)
    if existing is not None:
        return existing
    spec = CONSENT_TEXTS[consent_type]
    ttl = get_settings().consent_bki_ttl_days if consent_type == "CONSENT_CREDIT_BUREAU" else None
    consent = Consent(
        id=uuid.uuid4(), application_id=app.id, user_id=actor.user_id, consent_type=consent_type, subject_inn=app.applicant_inn,
        text_version=spec["version"], text_sha256=consent_text_sha256(consent_type), granted_at=now,
        expires_at=now + timedelta(days=ttl) if ttl else None, ip_address=actor.ip, user_agent=(actor.user_agent or "")[:512] or None,
    )
    session.add(consent)
    bump_version(session, app, actor, expected_version=expected_version, changes={}, allowed_statuses=(Status.DRAFT,))
    emit(session, "CONSENT_GIVEN", actor, application=app, payload={"consent_type": consent_type, "text_version": spec["version"], "expires_at": consent.expires_at.isoformat() if consent.expires_at else None})
    audit(session, actor, Command.GIVE_CONSENT.value, application_id=app.id, object_type="consent", object_id=str(consent.id), details={"consent_type": consent_type})
    return consent


def revoke_consent(session: Session, actor: Actor, app: Application, consent_type: str, *, expected_version: int | None) -> None:
    if consent_type not in CONSENT_TEXTS:
        raise NotFound("Неизвестный тип согласия", code="UNKNOWN_CONSENT")
    if app.status != Status.DRAFT:
        raise Conflict("После отправки отозвать согласие можно только отменой заявки", code="INVALID_TRANSITION")
    now = utcnow()
    existing = active_consents(consent_rows(session, app), now).get(consent_type)
    if existing is None:
        return
    existing.revoked_at = now
    bump_version(session, app, actor, expected_version=expected_version, changes={}, allowed_statuses=(Status.DRAFT,))
    emit(session, "CONSENT_REVOKED", actor, application=app, payload={"consent_type": consent_type, "text_version": existing.text_version})
    audit(session, actor, Command.REVOKE_CONSENT.value, application_id=app.id, object_type="consent", object_id=str(existing.id))


def _sniff(content: bytes) -> str | None:
    for magic, mime in MAGIC.items():
        if content.startswith(magic):
            return mime
    return None


def upload_document(session: Session, actor: Actor, app: Application, *, document_type: str, file_name: str, content: bytes, info_request_item_id: uuid.UUID | None, expected_version: int | None) -> Document:
    s = get_settings()
    if document_type not in DOCUMENT_TYPES:
        raise ValidationFailed(fields=[{"field": "document_type", "code": "INVALID_FORMAT", "message": "Неизвестный тип документа"}])
    if app.status == Status.INFO_REQUESTED:
        item = None
        if info_request_item_id is not None:
            item = session.execute(
                select(InfoRequestItem).join(InfoRequest, InfoRequest.id == InfoRequestItem.info_request_id)
                .where(InfoRequestItem.id == info_request_item_id, InfoRequest.application_id == app.id, InfoRequest.status == "OPEN")
            ).scalar_one_or_none()
        if item is None:
            raise Conflict("Сейчас можно загрузить только документы по пунктам запроса банка", code="INVALID_TRANSITION")
        if item.document_type and item.document_type != document_type:
            raise ValidationFailed(fields=[{"field": "document_type", "code": "INVALID_FORMAT", "message": "Этот пункт запроса ожидает другой документ"}])
    elif app.status != Status.DRAFT:
        raise invalid_transition(app.status, None, internal=False)
    if not content:
        raise ValidationFailed(fields=[{"field": "file", "code": "REQUIRED", "message": "Файл пустой"}])
    if len(content) > s.max_document_bytes:
        raise ValidationFailed(fields=[field_error("file", "DOCUMENT_TOO_LARGE")], code="DOCUMENT_TOO_LARGE")
    mime = _sniff(content)
    if mime is None:
        raise ValidationFailed(fields=[field_error("file", "DOCUMENT_TYPE_NOT_ALLOWED")], code="DOCUMENT_TYPE_NOT_ALLOWED")
    count = session.execute(select(func.count()).select_from(Document).where(Document.application_id == app.id, Document.deleted_at.is_(None))).scalar_one()
    if count >= s.max_documents_per_application:
        raise ValidationFailed("Можно загрузить не больше 20 файлов на заявку", code="TOO_MANY_DOCUMENTS")
    safe_name = "".join(ch for ch in (file_name or "document") if ch.isprintable() and ch not in '/\\:*?"<>|')[:200] or "document"
    key = uuid.uuid4().hex
    session.add(DocumentContent(storage_key=key, content=content))
    doc = Document(
        id=uuid.uuid4(), application_id=app.id, document_type=document_type, file_name=safe_name, mime_type=mime, size_bytes=len(content),
        sha256=hashlib.sha256(content).hexdigest(), uploaded_by=actor.user_id, uploaded_at=utcnow(), info_request_item_id=info_request_item_id, storage_key=key,
    )
    session.add(doc)
    bump_version(session, app, actor, expected_version=expected_version, changes={}, allowed_statuses=(Status.DRAFT, Status.INFO_REQUESTED))
    emit(session, "DOCUMENT_UPLOADED", actor, application=app, payload={"document_id": str(doc.id), "document_type": document_type, "size_bytes": len(content), "info_request_item_id": str(info_request_item_id) if info_request_item_id else None})
    audit(session, actor, Command.UPLOAD_DOCUMENT.value, application_id=app.id, object_type="document", object_id=str(doc.id))
    return doc


def delete_document(session: Session, actor: Actor, app: Application, document_id: uuid.UUID, *, expected_version: int | None) -> None:
    doc = session.execute(select(Document).where(Document.id == document_id, Document.application_id == app.id, Document.deleted_at.is_(None))).scalar_one_or_none()
    if doc is None:
        raise NotFound("Документ не найден", code="DOCUMENT_NOT_FOUND")
    if app.status != Status.DRAFT:
        raise Conflict("После отправки документы нельзя удалить", code="INVALID_TRANSITION")
    doc.deleted_at = utcnow()
    session.execute(update(DocumentContent).where(DocumentContent.storage_key == doc.storage_key).values(content=b"\x00"))
    bump_version(session, app, actor, expected_version=expected_version, changes={}, allowed_statuses=(Status.DRAFT,))
    emit(session, "DOCUMENT_DELETED", actor, application=app, payload={"document_id": str(doc.id), "document_type": doc.document_type})
    audit(session, actor, Command.DELETE_DOCUMENT.value, application_id=app.id, object_type="document", object_id=str(doc.id))


# ------------------------------------------------------------------------------ submit / respond / withdraw


def form_snapshot(app: Application) -> dict[str, Any]:
    from ..domain.dictionaries import FIELD_LABELS

    snap = {"product_code": app.product_code}
    for f in FIELD_LABELS:
        v = getattr(app, f)
        snap[f] = str(v) if isinstance(v, Decimal) else v
    snap["applicant_type"] = app.applicant_type
    return snap


def submit(session: Session, actor: Actor, app: Application, *, expected_version: int) -> Application:
    if app.status != Status.DRAFT:
        raise invalid_transition(app.status, None, internal=False)
    if expected_version != app.version:
        from ..errors import version_conflict

        raise version_conflict(app.version)
    product = _product(app.product_code)
    data = {f: getattr(app, f) for f in EDITABLE_FIELDS}
    errors = submit_errors(data, product)
    if app.applicant_inn and not inn_error(app.applicant_inn) and app.inn_check_status == "NOT_CHECKED":
        prefill(session, actor, app, expected_version=app.version, inn=None)
    if app.inn_check_status == "NOT_FOUND":
        errors.append(field_error("applicant_inn", "INN_NOT_FOUND"))
    active = active_consents(consent_rows(session, app), utcnow())
    for consent_type in CONSENT_TEXTS:
        if consent_type not in active:
            errors.append({"field": f"consents.{consent_type}", "code": "CONSENT_REQUIRED", "message": field_error("x", "CONSENT_REQUIRED")["message"]})
    if errors:
        raise ValidationFailed(fields=errors)
    duplicate = session.execute(
        select(Application.id).where(
            Application.applicant_inn == app.applicant_inn, Application.product_code == app.product_code, Application.id != app.id,
            Application.is_history.is_(False), Application.status.notin_(["DRAFT", "ISSUED", "DECLINED", "OFFER_DECLINED", "OFFER_EXPIRED", "CANCELLED"]),
        )
    ).first()
    if duplicate is not None:
        raise Conflict(field_error("x", "DUPLICATE_ACTIVE_APPLICATION")["message"], code="DUPLICATE_ACTIVE_APPLICATION", details={"application_id": str(duplicate[0])})
    now = utcnow()
    try:
        apply_transition(
            session, app, "T-03", actor, trigger=Command.SUBMIT, expected_version=app.version,
            changes={"submitted_snapshot": form_snapshot(app), "submitted_at": now, "applicant_type": applicant_type_for(app.applicant_inn)},
        )
        session.flush()
    except IntegrityError as exc:
        raise Conflict(field_error("x", "DUPLICATE_ACTIVE_APPLICATION")["message"], code="DUPLICATE_ACTIVE_APPLICATION") from exc
    enqueue(session, JobKind.COMPLETENESS_CHECK, app, correlation_id=actor.correlation_id)
    emit(session, "APPLICATION_SUBMITTED", actor, application=app, payload={"product_code": app.product_code, "purpose": app.purpose, "amount": str(app.amount), "term_months": app.term_months, "fill_duration_sec": int((now - app.created_at).total_seconds())})
    notify(session, app.client_user_id, "NTF_SUBMITTED", application=app)
    return app


def _validate_field_answer(app: Application, field: str, raw: Any) -> tuple[Any, dict[str, Any] | None]:
    value, err = normalize(field, raw)
    if err:
        return None, err
    if value is None:
        return None, field_error(field, "REQUIRED")
    probe = {f: getattr(app, f) for f in EDITABLE_FIELDS}
    probe[field] = value
    errs = [e for e in submit_errors(probe, _product(app.product_code)) if e["field"] == field]
    return value, (errs[0] if errs else None)


def respond_info(session: Session, actor: Actor, app: Application, *, expected_version: int, answers: list[dict[str, Any]]) -> Application:
    if app.status != Status.INFO_REQUESTED:
        raise invalid_transition(app.status, None, internal=False)
    ir = session.execute(select(InfoRequest).where(InfoRequest.application_id == app.id, InfoRequest.status == "OPEN").order_by(InfoRequest.created_at.desc()).limit(1)).scalar_one_or_none()
    if ir is None:
        raise Conflict(code="NO_OPEN_INFO_REQUEST")
    items = {str(i.id): i for i in session.execute(select(InfoRequestItem).where(InfoRequestItem.info_request_id == ir.id)).scalars()}
    by_item = {str(a["item_id"]): a for a in answers}
    unknown = [k for k in by_item if k not in items]
    if unknown:
        raise ValidationFailed(fields=[{"field": f"answers.{k}", "code": "UNKNOWN_ITEM", "message": "Пункт не относится к запросу"} for k in unknown])
    errors: list[dict[str, Any]] = []
    field_updates: dict[str, Any] = {}
    docs = {str(d.id): d for d in session.execute(select(Document).where(Document.application_id == app.id, Document.deleted_at.is_(None))).scalars()}
    for item_id, item in items.items():
        ans = by_item.get(item_id) or {}
        key = f"answers.{item_id}"
        if item.answer_type == "DOCUMENT":
            ids = [str(x) for x in (ans.get("document_ids") or [])]
            if not ids and item.required:
                errors.append({"field": key, "code": "REQUIRED", "message": "Загрузите документ"})
                continue
            bad = [i for i in ids if i not in docs or (item.document_type and docs[i].document_type != item.document_type)]
            if bad:
                errors.append({"field": key, "code": "INVALID_FORMAT", "message": "Документ не найден или другого типа"})
                continue
            item.document_ids = ids
        elif item.answer_type == "FIELD":
            raw = ans.get("answer_value")
            if raw in (None, "") and not item.required:
                continue
            value, err = _validate_field_answer(app, item.field_name, raw)
            if err:
                errors.append({**err, "field": key})
                continue
            field_updates[item.field_name] = value
            item.answer_value = str(value)
        else:
            txt = (ans.get("answer_text") or "").strip()
            if not txt and item.required:
                errors.append({"field": key, "code": "REQUIRED", "message": "Напишите ответ"})
                continue
            if len(txt) > 2000:
                errors.append({"field": key, "code": "INVALID_FORMAT", "message": "Ответ не длиннее 2000 символов"})
                continue
            item.answer_text = txt or None
        if ans.get("answer_text") and item.answer_type != "TEXT":
            item.answer_text = str(ans["answer_text"]).strip()[:2000]
    if errors:
        raise ValidationFailed(fields=errors)
    changed = []
    for field, value in field_updates.items():
        old = getattr(app, field)
        if old != value:
            changed.append(field)
            session.add(FieldChange(application_id=app.id, field_name=field, old_value=None if old is None else str(old), new_value=str(value), info_request_id=ir.id, changed_by=actor.user_id))
    now = utcnow()
    apply_transition(session, app, "T-10", actor, trigger=Command.RESPOND_INFO, expected_version=expected_version, changes=field_updates)
    ir.status, ir.answered_at = "ANSWERED", now
    enqueue(session, JobKind.COMPLETENESS_CHECK, app, correlation_id=actor.correlation_id)
    emit(session, "INFO_PROVIDED", actor, application=app, payload={"info_request_id": str(ir.id), "response_duration_sec": int((now - ir.created_at).total_seconds()), "changed_fields": changed})
    return app


def cancel_pending_jobs(session: Session, app: Application) -> None:
    session.execute(update(Job).where(Job.application_id == app.id, Job.status == "QUEUED").values(status="CANCELLED", finished_at=utcnow()))


def withdraw(session: Session, actor: Actor, app: Application, *, expected_version: int) -> Application:
    from_status = app.status
    tid = WITHDRAW_TRANSITIONS.get(Status(from_status), "T-41")
    apply_transition(session, app, tid, actor, trigger=Command.WITHDRAW, expected_version=expected_version, changes={"cancel_reason": "CL_WITHDRAWN"})
    cancel_pending_jobs(session, app)
    session.execute(update(InfoRequest).where(InfoRequest.application_id == app.id, InfoRequest.status == "OPEN").values(status="CANCELLED"))
    emit(session, "APPLICATION_CANCELLED", actor, application=app, payload={"cancel_reason": "CL_WITHDRAWN", "from_status": from_status})
    return app


# ------------------------------------------------------------------------------ offer and signing


def accept_offer(session: Session, actor: Actor, app: Application, *, expected_version: int, option_id: uuid.UUID) -> Application:
    offer = session.get(Offer, app.current_offer_id) if app.current_offer_id else None
    option = session.get(OfferOption, option_id)
    if offer is None or option is None or option.offer_id != offer.id:
        if app.status != Status.OFFER_PENDING:
            raise invalid_transition(app.status, None, internal=False)
        raise ValidationFailed("Вариант не относится к текущему предложению", code="OPTION_NOT_IN_OFFER")
    now = utcnow()
    apply_transition(
        session, app, "T-33", actor, trigger=Command.ACCEPT_OFFER, expected_version=expected_version,
        changes={"final_product_code": option.product_code, "final_amount": option.amount, "final_term_months": option.term_months, "final_rate_percent": option.rate_percent, "final_monthly_payment": option.monthly_payment, "final_option_id": option.id},
    )
    offer.status, offer.selected_option_id = "ACCEPTED", option.id
    enqueue(session, JobKind.PREPARE_DOCUMENTS, app, correlation_id=actor.correlation_id, idempotency_key=f"PREPARE_DOCUMENTS:{app.id}:{option.id}")
    emit(session, "OFFER_ACCEPTED", actor, application=app, payload={"offer_id": str(offer.id), "option_id": str(option.id), "option_type": option.option_type, "product_code": option.product_code, "amount": str(option.amount), "term_months": option.term_months, "decision_sec": int((now - offer.created_at).total_seconds())})
    return app


def revoke_codes(session: Session, app: Application) -> None:
    now = utcnow()
    codes = list(session.execute(select(SigningCode).where(SigningCode.application_id == app.id, SigningCode.used_at.is_(None), SigningCode.revoked_at.is_(None))).scalars())
    for c in codes:
        c.revoked_at = now
        if c.notification_id:
            session.execute(update(Notification).where(Notification.id == c.notification_id).values(body=SIGNING_CODE_EXPIRED_TEXT))


def decline_offer(session: Session, actor: Actor, app: Application, *, expected_version: int, reason_code: str | None) -> Application:
    if reason_code is not None and reason_code not in OFFER_DECLINE_REASONS:
        raise ValidationFailed(fields=[{"field": "reason_code", "code": "INVALID_FORMAT", "message": "Неизвестная причина"}])
    tid = DECLINE_OFFER_TRANSITIONS.get(Status(app.status))
    if tid is None:
        raise invalid_transition(app.status, None, internal=False)
    apply_transition(session, app, tid, actor, trigger=Command.DECLINE_OFFER, expected_version=expected_version)
    offer = session.get(Offer, app.current_offer_id) if app.current_offer_id else None
    if offer is not None:
        offer.status, offer.decline_reason_code = "DECLINED", reason_code
    revoke_codes(session, app)
    cancel_pending_jobs(session, app)
    emit(session, "OFFER_DECLINED", actor, application=app, payload={"offer_id": str(offer.id) if offer else None, "decline_reason_code": reason_code})
    return app


def _current_package(session: Session, app: Application) -> DocumentPackage:
    package = session.execute(select(DocumentPackage).where(DocumentPackage.application_id == app.id).order_by(DocumentPackage.created_at.desc()).limit(1)).scalar_one_or_none()
    if package is None:
        raise Conflict("Документы еще готовятся", code="DOCUMENTS_NOT_READY")
    return package


def request_signing_code(session: Session, actor: Actor, app: Application) -> dict[str, Any]:
    from ..security import hash_signing_code, new_signing_code

    s = get_settings()
    if app.status != Status.SIGNING:
        raise invalid_transition(app.status, None, internal=False)
    now = utcnow()
    issued_last_hour = session.execute(select(func.count()).select_from(SigningCode).where(SigningCode.application_id == app.id, SigningCode.issued_at > now - timedelta(hours=1))).scalar_one()
    if issued_last_hour >= s.signing_codes_per_hour:
        oldest = session.execute(select(func.min(SigningCode.issued_at)).where(SigningCode.application_id == app.id, SigningCode.issued_at > now - timedelta(hours=1))).scalar_one()
        minutes = max(1, int(((oldest + timedelta(hours=1)) - now).total_seconds() // 60) + 1)
        raise TooManyRequests(f"Слишком много запросов кода, попробуйте через {minutes} мин.", code="SIGNING_CODE_LIMIT", details={"retry_after_minutes": minutes})
    package = _current_package(session, app)
    hashes = sorted(d.sha256 for d in session.execute(select(GeneratedDocument).where(GeneratedDocument.package_id == package.id)).scalars())
    revoke_codes(session, app)
    code = new_signing_code()
    code_id = uuid.uuid4()
    expires = now + timedelta(seconds=s.signing_code_ttl_seconds)
    n = notify(session, app.client_user_id, "NTF_SIGNING_CODE", application=app, notification_expires_at=expires, code=code)
    session.add(SigningCode(id=code_id, application_id=app.id, package_id=package.id, code_hash=hash_signing_code(code_id, code), documents_sha256=hashes, issued_at=now, expires_at=expires, attempts=0, notification_id=n.id))
    emit(session, "SIGNING_CODE_ISSUED", actor, application=app, payload={"signing_code_id": str(code_id), "expires_at": expires.isoformat()})
    audit(session, actor, Command.REQUEST_SIGNING_CODE.value, application_id=app.id, object_type="signing_code", object_id=str(code_id))
    out = {"signing_code_id": str(code_id), "expires_at": expires.isoformat().replace("+00:00", "Z"), "ttl_seconds": s.signing_code_ttl_seconds, "attempts_left": s.signing_code_max_attempts}
    if s.demo_mode:
        out["code"] = code
        out["demo_note"] = "Код показан в ответе, потому что включен демо-режим: в прототипе нет SMS и email."
    return out


def _register_failed_attempt(code_id: uuid.UUID, application_id: uuid.UUID, actor: Actor, reason: str) -> int:
    """Commit the failed attempt independently of the rejected command (the counter must survive the rollback)."""
    s = get_settings()
    with session_scope() as other:
        sc = other.execute(select(SigningCode).where(SigningCode.id == code_id).with_for_update()).scalar_one()
        sc.attempts += 1
        if sc.attempts >= s.signing_code_max_attempts:
            sc.revoked_at = utcnow()
            if sc.notification_id:
                other.execute(update(Notification).where(Notification.id == sc.notification_id).values(body=SIGNING_CODE_EXPIRED_TEXT))
        emit(other, "SIGNING_CODE_REJECTED", actor, application_id=application_id, payload={"signing_code_id": str(code_id), "attempt": sc.attempts, "reason": reason})
        audit(other, actor, Command.SIGN.value, result="DENIED", application_id=application_id, object_type="signing_code", object_id=str(code_id), details={"reason": reason})
        return s.signing_code_max_attempts - sc.attempts


def sign(session: Session, actor: Actor, app: Application, *, expected_version: int, code: str) -> Application:
    from ..security import code_matches

    s = get_settings()
    if app.status != Status.SIGNING:
        raise invalid_transition(app.status, None, internal=False)
    if expected_version != app.version:
        from ..errors import version_conflict

        raise version_conflict(app.version)
    now = utcnow()
    sc = session.execute(
        select(SigningCode).where(SigningCode.application_id == app.id, SigningCode.used_at.is_(None), SigningCode.revoked_at.is_(None)).order_by(SigningCode.issued_at.desc()).limit(1)
    ).scalar_one_or_none()
    if sc is None:
        raise ValidationFailed("Получите код подтверждения", code="SIGNING_CODE_REQUIRED")
    if sc.expires_at <= now:
        _register_failed_attempt(sc.id, app.id, actor, "EXPIRED")
        raise ValidationFailed("Код больше не действует, получите новый", code="SIGNING_CODE_EXPIRED")
    if not code.isdigit() or len(code) != 6 or not code_matches(sc.id, code, sc.code_hash):
        left = _register_failed_attempt(sc.id, app.id, actor, "WRONG" if sc.attempts + 1 < s.signing_code_max_attempts else "ATTEMPTS_EXCEEDED")
        if left <= 0:
            raise ValidationFailed("Неверный код. Попытки закончились, получите новый код", code="SIGNING_ATTEMPTS_EXCEEDED", details={"attempts_left": 0})
        raise ValidationFailed(f"Неверный код, осталось попыток: {left}", code="SIGNING_CODE_INVALID", details={"attempts_left": left})
    package = session.get(DocumentPackage, sc.package_id)
    try:
        ext = integrations.register_signature(
            package.external_package_id,
            {"documents_sha256": sc.documents_sha256, "signing_code_id": str(sc.id), "signer_ref": str(actor.user_id), "signed_at": now.isoformat()},
            idempotency_key=f"SIGN:{app.id}:{sc.id}", correlation_id=actor.correlation_id,
        )
    except integrations.OperationError as exc:
        log.warning("edo signature registration failed", extra={"fields": {"application_id": str(app.id), "code": exc.code}})
        raise ServiceUnavailable("Не удалось зарегистрировать подпись, попробуйте еще раз через минуту", code="SIGNING_SERVICE_UNAVAILABLE") from exc
    apply_transition(session, app, "T-39", actor, trigger=Command.SIGN, expected_version=expected_version)
    sc.used_at = now
    if sc.notification_id:
        session.execute(update(Notification).where(Notification.id == sc.notification_id).values(body="Код использован для подписания документов."))
    package.status = "SIGNED"
    session.add(Signature(id=uuid.uuid4(), application_id=app.id, signing_code_id=sc.id, package_id=package.id, external_signature_id=ext.get("signature_id"), documents_sha256=sc.documents_sha256, signed_at=now, ip_address=actor.ip, user_agent=(actor.user_agent or "")[:512] or None))
    enqueue(session, JobKind.ISSUE_LOAN, app, correlation_id=actor.correlation_id, idempotency_key=f"ISSUE_LOAN:{app.id}")
    emit(session, "DOCUMENTS_SIGNED", actor, application=app, payload={"signing_code_id": str(sc.id), "documents_sha256": sc.documents_sha256})
    return app

