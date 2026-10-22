"""Read models: client view (no internal status, score, grade, thresholds) and the employee card."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..domain.catalog import credit_line_view
from ..domain.configs import get_registry
from ..domain.dictionaries import (
    CLIENT_STATUS_TEXTS,
    CONSENT_TEXTS,
    DOCUMENT_TYPES,
    EXTRA_REASON_CODES,
    FIELD_LABELS,
    PROGRESS_STEPS,
    PURPOSES,
    fmt_date,
    fmt_dt,
    fmt_money,
    render,
)
from ..domain.money import annuity_payment
from ..domain.policy import rate_for
from ..domain.statemachine import available_actions
from ..domain.validation import submit_errors, warnings_for
from ..enums import ActorType, ClientStatus, Status
from ..models import (
    Application,
    AuditLog,
    Comment,
    Consent,
    Decision,
    Document,
    DocumentPackage,
    Event,
    FieldChange,
    GeneratedDocument,
    InfoRequest,
    InfoRequestItem,
    Loan,
    Notification,
    Offer,
    OfferOption,
    ScoringResult,
    SigningCode,
    SourceSnapshot,
    StatusHistory,
    User,
)
from .core import Actor, guard_context, utcnow

STEP = {
    Status.DRAFT: 1, Status.SUBMITTED: 2, Status.ENRICHMENT: 3, Status.EXTERNAL_SERVICE_UNAVAILABLE: 3, Status.SCORING: 3,
    Status.DECISIONING: 3, Status.INFO_REQUESTED: 3, Status.MANUAL_REVIEW: 4, Status.IN_REVIEW: 4, Status.PENDING_RISK_APPROVAL: 4,
    Status.OFFER_PENDING: 5, Status.OFFER_ACCEPTED: 6, Status.SIGNING: 6, Status.SIGNED: 7, Status.ISSUED: 8,
}
FAILED_STAGE_CLIENT = {
    Status.SUBMITTED: (ClientStatus.CHECKING, 3, "CHECKING_ERROR"),
    Status.ENRICHMENT: (ClientStatus.CHECKING, 3, "CHECKING_ERROR"),
    Status.SCORING: (ClientStatus.CHECKING, 3, "CHECKING_ERROR"),
    Status.DECISIONING: (ClientStatus.CHECKING, 3, "CHECKING_ERROR"),
    Status.OFFER_ACCEPTED: (ClientStatus.DOCUMENTS, 6, "DOCUMENTS_ERROR"),
    Status.SIGNED: (ClientStatus.PAYOUT, 7, "PAYOUT_ERROR"),
}
NEXT_ACTION_LABELS = {
    ClientStatus.FILLING: "Продолжить заполнение",
    ClientStatus.ACTION_REQUIRED: "Ответить на запрос банка",
    ClientStatus.DECISION_READY: "Посмотреть решение",
    ClientStatus.DOCUMENTS: "Подписать документы",
}


def money_str(v: Decimal | None) -> str | None:
    return None if v is None else str(v)


def iso(v: datetime | None) -> str | None:
    return None if v is None else v.isoformat().replace("+00:00", "Z")


def reason_dictionary() -> dict[str, dict[str, Any]]:
    pol = get_registry().policy_content()
    return {**pol["reason_codes"], **EXTRA_REASON_CODES}


def _humanize(values: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in values.items():
        if k in ("registration_date", "eligible_date", "due_at"):
            out[k] = fmt_date(v) if isinstance(v, str) and len(v) == 10 else v
        elif k in ("delinquency_amount", "tax_arrears_amount", "allowed_payment", "requested_payment", "amount"):
            out[k] = fmt_money(v)
        elif isinstance(v, list):
            out[k] = ", ".join(map(str, v))
        else:
            out[k] = v
    return out


def client_reasons(codes: list[str], details: dict[str, Any]) -> list[dict[str, str | None]]:
    """Visibility rule: FULL texts in dictionary order; a GENERIC reason hides all others; NONE is never shown."""
    dictionary = reason_dictionary()
    ordered = [c for c in dictionary if c in codes]
    generic = [c for c in ordered if dictionary[c]["client_visibility"] == "GENERIC"]
    visible = generic[:1] if generic else [c for c in ordered if dictionary[c]["client_visibility"] == "FULL"]
    out = []
    for code in visible:
        entry = dictionary[code]
        values = _humanize(details.get(code, {}))
        out.append({"text": render(entry["client_text"], values), "next_step": render(entry.get("client_next_step"), values)})
    return out


def employee_reasons(codes: list[str], details: dict[str, Any], context: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    dictionary = reason_dictionary()
    out = []
    for code in codes:
        entry = dictionary.get(code, {})
        values = {**(context or {}), **details.get(code, {})}
        out.append(
            {
                "code": code,
                "employee_text": render(entry.get("employee_text"), values),
                "client_text": render(entry.get("client_text"), _humanize(values)),
                "client_visibility": entry.get("client_visibility"),
            }
        )
    return out


class AppContext:
    """Related rows loaded once per view."""

    def __init__(self, session: Session, app: Application):
        self.session = session
        self.app = app
        self.offer = session.get(Offer, app.current_offer_id) if app.current_offer_id else None
        self.open_info_request = session.execute(
            select(InfoRequest).where(InfoRequest.application_id == app.id, InfoRequest.status == "OPEN").order_by(InfoRequest.created_at.desc()).limit(1)
        ).scalar_one_or_none()
        self.final_decision = session.execute(
            select(Decision).where(Decision.application_id == app.id, Decision.status == "FINAL").order_by(Decision.created_at.desc()).limit(1)
        ).scalar_one_or_none()
        self.history = list(session.execute(select(StatusHistory).where(StatusHistory.application_id == app.id).order_by(StatusHistory.id)).scalars())

    def ever_manual(self) -> bool:
        return self.app.manual_review_required or any(h.to_status in (Status.MANUAL_REVIEW, Status.IN_REVIEW) for h in self.history)


def client_status_of(ctx: AppContext) -> tuple[ClientStatus, int, str]:
    """(client_status, progress_step, text key) by the mapping of application-states.md, section 3.1."""
    app = ctx.app
    st = Status(app.status)
    if st == Status.DRAFT:
        return ClientStatus.FILLING, 1, "FILLING"
    if st == Status.SUBMITTED:
        return (ClientStatus.SENT, 2, "SENT") if app.info_request_count == 0 else (ClientStatus.CHECKING, 3, "CHECKING")
    if st == Status.EXTERNAL_SERVICE_UNAVAILABLE:
        return ClientStatus.CHECKING, 3, "CHECKING_DELAYED"
    if st in (Status.ENRICHMENT, Status.SCORING, Status.DECISIONING):
        return ClientStatus.CHECKING, 3, "CHECKING"
    if st == Status.INFO_REQUESTED:
        step = 4 if ctx.open_info_request is not None and ctx.open_info_request.source == "UNDERWRITER" else 3
        return ClientStatus.ACTION_REQUIRED, step, "ACTION_REQUIRED"
    if st in (Status.MANUAL_REVIEW, Status.IN_REVIEW, Status.PENDING_RISK_APPROVAL):
        return ClientStatus.SPECIALIST_REVIEW, 4, "SPECIALIST_REVIEW"
    if st == Status.OFFER_PENDING:
        counter = ctx.offer is not None and ctx.offer.outcome == "COUNTER_OFFER"
        return ClientStatus.DECISION_READY, 5, "DECISION_READY_COUNTER" if counter else "DECISION_READY_APPROVED"
    if st in (Status.OFFER_ACCEPTED, Status.SIGNING):
        return ClientStatus.DOCUMENTS, 6, "DOCUMENTS"
    if st == Status.SIGNED:
        return ClientStatus.PAYOUT, 7, "PAYOUT"
    if st == Status.ISSUED:
        return ClientStatus.COMPLETED, 8, "COMPLETED"
    if st == Status.PROCESSING_ERROR:
        cs, step, key = FAILED_STAGE_CLIENT.get(app.failed_stage, (ClientStatus.CHECKING, 3, "CHECKING_ERROR"))
        return cs, step, key
    last_step = STEP.get(ctx.history[-1].from_status, 1) if ctx.history and ctx.history[-1].from_status else 1
    if st == Status.DECLINED:
        return ClientStatus.REJECTED, 5, "REJECTED"
    if st == Status.OFFER_EXPIRED:
        return ClientStatus.EXPIRED, last_step, "EXPIRED"
    return ClientStatus.WITHDRAWN, last_step, "WITHDRAWN"


def _remaining_steps(app: Application, product: dict[str, Any], consents_ok: bool) -> int:
    data = {f: getattr(app, f) for f in FIELD_LABELS}
    n = 0
    if not app.applicant_inn or not app.representative_role:
        n += 1
    if any(e["field"] not in ("applicant_inn", "representative_role") for e in submit_errors(data, product)):
        n += 1
    if product["required_documents"]:
        n += 1
    if not consents_ok:
        n += 1
    return max(n, 1)


def status_text(ctx: AppContext, key: str, *, product: dict[str, Any], consents_ok: bool) -> dict[str, Any]:
    app = ctx.app
    tpl = CLIENT_STATUS_TEXTS[key]
    values: dict[str, Any] = {}
    deadline: datetime | None = None
    extra: list[str] = []
    if key == "FILLING":
        values["n"] = _remaining_steps(app, product, consents_ok)
    elif key == "SENT":
        deadline = app.status_changed_at + timedelta(minutes=1)
    elif key == "CHECKING":
        deadline = app.status_changed_at + timedelta(minutes=5)
    elif key == "CHECKING_DELAYED":
        deadline = app.status_changed_at + timedelta(minutes=20)
    elif key in ("CHECKING_ERROR", "DOCUMENTS_ERROR", "PAYOUT_ERROR"):
        deadline = app.status_changed_at + timedelta(hours=4)
    elif key == "ACTION_REQUIRED" and ctx.open_info_request is not None:
        deadline = ctx.open_info_request.due_at
        values["k"] = ctx.session.execute(select(func.count()).select_from(InfoRequestItem).where(InfoRequestItem.info_request_id == ctx.open_info_request.id)).scalar_one()
    elif key == "SPECIALIST_REVIEW":
        deadline = app.review_due_at
        codes = app.manual_review_reasons or []
        dictionary = reason_dictionary()
        extra = [dictionary[c]["client_text"] for c in codes if c in dictionary and dictionary[c]["client_visibility"] == "FULL" and dictionary[c]["client_text"]]
    elif key.startswith("DECISION_READY") or key == "DOCUMENTS":
        deadline = ctx.offer.expires_at if ctx.offer else None
    elif key == "PAYOUT":
        deadline = app.status_changed_at + timedelta(minutes=1)
    elif key == "COMPLETED":
        loan = ctx.session.execute(select(Loan).where(Loan.application_id == app.id)).scalar_one_or_none()
        if loan is not None:
            if loan.operation_type == "CREDIT_LINE_LIMIT":
                tpl = CLIENT_STATUS_TEXTS["COMPLETED_LINE"]
            values.update(account=loan.account_number_masked, limit=fmt_money(loan.amount), first_payment_date=fmt_date(loan.first_payment_date), monthly_payment=fmt_money(loan.monthly_payment))
    elif key == "REJECTED" and ctx.final_decision is not None:
        reasons = client_reasons(ctx.final_decision.reason_codes, ctx.final_decision.reason_details)
        values["reason"] = " ".join(r["text"] for r in reasons if r["text"])
        values["next_step"] = " ".join(r["next_step"] for r in reasons if r["next_step"])
    elif key == "EXPIRED":
        deadline = ctx.offer.expires_at if ctx.offer else None
        values["due"] = fmt_dt(deadline)
    elif key == "WITHDRAWN" and app.cancel_reason:
        entry = EXTRA_REASON_CODES[app.cancel_reason]
        due_at = ctx.session.execute(
            select(InfoRequest.due_at).where(InfoRequest.application_id == app.id).order_by(InfoRequest.created_at.desc()).limit(1)
        ).scalar_one_or_none()
        extra = [render(entry["client_text"], {"due_at": fmt_dt(due_at), "draft_ttl_days": get_registry().policy_content()["process"]["draft_ttl_days"]}) or ""]
    if deadline is not None:
        values.setdefault("due", fmt_dt(deadline))
    return {
        "title": render(tpl["title"], values),
        "what_is_happening": render(tpl["what"], values),
        "what_next": render(tpl["next"], values),
        "deadline_text": render(tpl["eta"], values) or None,
        "deadline_at": iso(deadline),
        "notes": extra,
    }


def progress(ctx: AppContext, current_step: int, client_status: ClientStatus) -> list[dict[str, Any]]:
    terminal = client_status in (ClientStatus.REJECTED, ClientStatus.WITHDRAWN, ClientStatus.EXPIRED)
    skipped_review = not ctx.ever_manual() and current_step > 4
    steps = []
    for i, title in enumerate(PROGRESS_STEPS, start=1):
        if i == 4 and skipped_review:
            state = "SKIPPED"
        elif i < current_step or (client_status == ClientStatus.COMPLETED and i == current_step):
            state = "DONE"
        elif i == current_step:
            state = "STOPPED" if terminal else ("ACTION_REQUIRED" if client_status == ClientStatus.ACTION_REQUIRED else "CURRENT")
        else:
            state = "PENDING"
        steps.append({"step": i, "title": title, "state": state, "note": "не потребовался" if state == "SKIPPED" else None})
    return steps


def option_view(o: OfferOption, requested_amount: Decimal | None, requested_term: int | None) -> dict[str, Any]:
    diff = None
    if o.product_code == "CREDIT_LINE":
        diff = "кредитная линия"
    elif requested_amount is not None and o.amount < requested_amount:
        diff = f"на {fmt_money(requested_amount - o.amount)} меньше"
    elif requested_term is not None and o.term_months > requested_term:
        diff = f"на {o.term_months - requested_term} мес. дольше"
    elif requested_term is not None and o.term_months < requested_term:
        diff = f"на {requested_term - o.term_months} мес. короче"
    product = get_registry().policy_content()["products"][o.product_code]
    view = {
        "id": str(o.id),
        "option_type": o.option_type,
        "product_code": o.product_code,
        "product_name": product["name"],
        "amount": str(o.amount),
        "term_months": o.term_months,
        "rate_percent": str(o.rate_percent),
        "monthly_payment": str(o.monthly_payment),
        "total_payment": str(o.total_payment),
        "overpayment": str(o.overpayment),
        "requires_owner_guarantee": o.requires_owner_guarantee,
        "requires_collateral": o.requires_collateral,
        "tranche_max_term_months": o.tranche_max_term_months,
        "recommended": o.recommended,
        "difference_text": diff,
    }
    if o.product_code == "CREDIT_LINE":
        view["credit_line"] = credit_line_view(o.amount, o.rate_percent, o.tranche_max_term_months or 12)
    return view


def offer_view(ctx: AppContext) -> dict[str, Any] | None:
    offer = ctx.offer
    if offer is None:
        return None
    app = ctx.app
    decision = ctx.session.get(Decision, offer.decision_id)
    options = list(ctx.session.execute(select(OfferOption).where(OfferOption.offer_id == offer.id).order_by(OfferOption.position)).scalars())
    requested_payment = None
    if decision is not None and decision.grade and app.amount and app.term_months:
        rate = rate_for(get_registry().policy_content(), app.product_code, decision.grade)
        requested_payment = str(annuity_payment(app.amount, rate, app.term_months))
    codes = list(decision.reason_codes) if decision else []
    return {
        "id": str(offer.id),
        "outcome": offer.outcome,
        "status": offer.status,
        "expires_at": iso(offer.expires_at),
        "expires_text": fmt_dt(offer.expires_at),
        "selected_option_id": str(offer.selected_option_id) if offer.selected_option_id else None,
        "requested": {"amount": money_str(app.amount), "term_months": app.term_months, "monthly_payment": requested_payment},
        "reasons": client_reasons(codes, decision.reason_details if decision else {}),
        "options": [option_view(o, app.amount, app.term_months) for o in options],
    }


def signing_view(ctx: AppContext) -> dict[str, Any] | None:
    app = ctx.app
    package = ctx.session.execute(
        select(DocumentPackage).where(DocumentPackage.application_id == app.id).order_by(DocumentPackage.created_at.desc()).limit(1)
    ).scalar_one_or_none()
    if package is None:
        return None
    docs = ctx.session.execute(select(GeneratedDocument).where(GeneratedDocument.package_id == package.id)).scalars()
    now = utcnow()
    code = ctx.session.execute(
        select(SigningCode).where(SigningCode.application_id == app.id, SigningCode.used_at.is_(None), SigningCode.revoked_at.is_(None), SigningCode.expires_at > now)
        .order_by(SigningCode.issued_at.desc()).limit(1)
    ).scalar_one_or_none()
    from ..config import get_settings

    return {
        "package_id": str(package.id),
        "contract_number": package.contract_number,
        "status": package.status,
        "documents": [{"id": str(d.id), "document_type": d.document_type, "title": d.title, "sha256": d.sha256} for d in docs],
        "active_code": None if code is None else {"expires_at": iso(code.expires_at), "attempts_left": get_settings().signing_code_max_attempts - code.attempts},
        "note": "Подписание в прототипе смоделировано: код подтверждения показывается здесь, в кабинете. В реальном продукте используется электронная подпись.",
    }


def loan_view(session: Session, app: Application) -> dict[str, Any] | None:
    loan = session.execute(select(Loan).where(Loan.application_id == app.id)).scalar_one_or_none()
    if loan is None:
        return None
    return {
        "contract_number": loan.contract_number,
        "account_number_masked": loan.account_number_masked,
        "operation_type": loan.operation_type,
        "product_code": loan.product_code,
        "amount": str(loan.amount),
        "rate_percent": str(loan.rate_percent),
        "term_months": loan.term_months,
        "monthly_payment": str(loan.monthly_payment),
        "issued_at": iso(loan.issued_at),
        "first_payment_date": loan.first_payment_date.isoformat(),
    }


def info_request_view(session: Session, app: Application, ir: InfoRequest | None, *, staff: bool) -> dict[str, Any] | None:
    if ir is None:
        return None
    items = session.execute(select(InfoRequestItem).where(InfoRequestItem.info_request_id == ir.id).order_by(InfoRequestItem.position)).scalars()
    out_items = []
    for it in items:
        item = {
            "id": str(it.id),
            "answer_type": it.answer_type,
            "field_name": it.field_name,
            "field_label": FIELD_LABELS.get(it.field_name) if it.field_name else None,
            "current_value": (lambda v: None if v is None else str(v))(getattr(app, it.field_name)) if it.field_name else None,
            "document_type": it.document_type,
            "document_title": DOCUMENT_TYPES[it.document_type]["title"] if it.document_type else None,
            "client_text": it.client_text,
            "required": it.required,
            "answer_text": it.answer_text,
            "answer_value": it.answer_value,
            "document_ids": it.document_ids or [],
        }
        if staff:
            item["reason_code"] = it.reason_code
            item["employee_text"] = it.employee_text
        out_items.append(item)
    view = {
        "id": str(ir.id),
        "status": ir.status,
        "due_at": iso(ir.due_at),
        "due_text": fmt_dt(ir.due_at),
        "created_at": iso(ir.created_at),
        "answered_at": iso(ir.answered_at),
        "items": out_items,
    }
    if staff:
        view["source"] = ir.source
        view["cycle_number"] = ir.cycle_number
    return view


def consent_rows(session: Session, app: Application) -> list[Consent]:
    return list(session.execute(select(Consent).where(Consent.application_id == app.id).order_by(Consent.granted_at)).scalars())


def active_consents(rows: list[Consent], now: datetime) -> dict[str, Consent]:
    out = {}
    for c in rows:
        if c.revoked_at is None and (c.expires_at is None or c.expires_at > now):
            out[c.consent_type] = c
    return out


def documents_view(session: Session, app: Application) -> list[dict[str, Any]]:
    docs = session.execute(select(Document).where(Document.application_id == app.id, Document.deleted_at.is_(None)).order_by(Document.uploaded_at)).scalars()
    return [
        {
            "id": str(d.id),
            "document_type": d.document_type,
            "document_title": DOCUMENT_TYPES[d.document_type]["title"],
            "file_name": d.file_name,
            "mime_type": d.mime_type,
            "size_bytes": d.size_bytes,
            "sha256": d.sha256,
            "uploaded_at": iso(d.uploaded_at),
            "info_request_item_id": str(d.info_request_item_id) if d.info_request_item_id else None,
        }
        for d in docs
    ]


def registry_view(app: Application) -> dict[str, Any] | None:
    reg = app.registry_data
    if not reg:
        return None
    founders = reg.get("founders") or []
    guarantor = None
    if founders:
        guarantor = max(founders, key=lambda f: Decimal(str(f.get("share_percent") or 0)))["name"]
    return {
        "source": "ЕГРЮЛ" if app.applicant_type == "LEGAL_ENTITY" else "ЕГРИП",
        "fetched_at": iso(app.prefilled_at),
        "applicant_type": app.applicant_type,
        "company_full_name": reg.get("company_full_name"),
        "company_short_name": reg.get("company_short_name"),
        "ogrn": reg.get("ogrn"),
        "registration_date": reg.get("registration_date"),
        "company_status": reg.get("company_status"),
        "okved_main_code": reg.get("okved_main_code"),
        "okved_main_name": reg.get("okved_main_name"),
        "legal_address_region": reg.get("legal_address_region"),
        "director_full_name": reg.get("director_full_name"),
        "founders": founders,
        "guarantor_full_name": guarantor if app.applicant_type == "LEGAL_ENTITY" else None,
        "sme_category": reg.get("sme_category"),
        "tax_regime": reg.get("tax_regime"),
        "employees_count": reg.get("employees_count"),
    }


def form_view(app: Application) -> dict[str, Any]:
    out = {}
    for f in FIELD_LABELS:
        v = getattr(app, f)
        out[f] = str(v) if isinstance(v, Decimal) else v
    return out


def client_timeline(ctx: AppContext) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    last = None
    for h in ctx.history:
        cs = _client_status_for_status(h)
        if cs != last:
            items.append({"client_status": cs, "title": _title_for(cs), "at": iso(h.occurred_at)})
            last = cs
    return items


def _client_status_for_status(h: StatusHistory) -> str:
    st = h.to_status
    mapping = {
        Status.DRAFT: ClientStatus.FILLING, Status.ENRICHMENT: ClientStatus.CHECKING, Status.EXTERNAL_SERVICE_UNAVAILABLE: ClientStatus.CHECKING,
        Status.SCORING: ClientStatus.CHECKING, Status.DECISIONING: ClientStatus.CHECKING, Status.INFO_REQUESTED: ClientStatus.ACTION_REQUIRED,
        Status.MANUAL_REVIEW: ClientStatus.SPECIALIST_REVIEW, Status.IN_REVIEW: ClientStatus.SPECIALIST_REVIEW, Status.PENDING_RISK_APPROVAL: ClientStatus.SPECIALIST_REVIEW,
        Status.OFFER_PENDING: ClientStatus.DECISION_READY, Status.OFFER_ACCEPTED: ClientStatus.DOCUMENTS, Status.SIGNING: ClientStatus.DOCUMENTS,
        Status.SIGNED: ClientStatus.PAYOUT, Status.ISSUED: ClientStatus.COMPLETED, Status.DECLINED: ClientStatus.REJECTED,
        Status.CANCELLED: ClientStatus.WITHDRAWN, Status.OFFER_DECLINED: ClientStatus.WITHDRAWN, Status.OFFER_EXPIRED: ClientStatus.EXPIRED,
    }
    if st == Status.SUBMITTED:
        return ClientStatus.SENT if h.trigger == "SUBMIT" else ClientStatus.CHECKING
    if st == Status.PROCESSING_ERROR:
        return ClientStatus.CHECKING
    return mapping[Status(st)]


def _title_for(cs: str) -> str:
    key = {"CHECKING": "CHECKING", "DECISION_READY": "DECISION_READY_APPROVED"}.get(cs, cs)
    if cs == "DECISION_READY":
        return "Решение готово"
    return CLIENT_STATUS_TEXTS[key]["title"]


def required_documents_view(product: dict[str, Any], docs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    present = {d["document_type"] for d in docs}
    return [
        {"document_type": d, "title": DOCUMENT_TYPES[d]["title"], "purpose": DOCUMENT_TYPES[d]["purpose"], "uploaded": d in present}
        for d in product["required_documents"]
    ]


def client_application_view(session: Session, app: Application, actor: Actor) -> dict[str, Any]:
    """Client API: client_status and texts; never internal status, score, grade, thresholds, comments."""
    pol = get_registry().policy_content()
    product = pol["products"][app.product_code]
    ctx = AppContext(session, app)
    now = utcnow()
    consents = consent_rows(session, app)
    active = active_consents(consents, now)
    consents_ok = all(t in active for t in CONSENT_TEXTS)
    cs, step, key = client_status_of(ctx)
    gctx = guard_context(session, app, actor, now=now)
    docs = documents_view(session, app)
    view: dict[str, Any] = {
        "id": str(app.id),
        "application_number": app.application_number,
        "version": app.version,
        "product_code": app.product_code,
        "product_name": product["name"],
        "purpose": app.purpose,
        "purpose_title": PURPOSES[app.purpose]["title"],
        "form": form_view(app),
        "applicant_type": app.applicant_type,
        "inn_check_status": app.inn_check_status,
        "company": registry_view(app),
        "early_warnings": app.early_warnings or [],
        "client_status": cs.value,
        "client_status_text": status_text(ctx, key, product=product, consents_ok=consents_ok),
        "progress_step": step,
        "progress": progress(ctx, step, cs),
        "action_required": cs == ClientStatus.ACTION_REQUIRED,
        "available_actions": available_actions(app.status, gctx, app.is_history),
        "consents": [
            {"consent_type": t, "given": t in active, "granted_at": iso(active[t].granted_at) if t in active else None, "expires_at": iso(active[t].expires_at) if t in active else None, "text_version": CONSENT_TEXTS[t]["version"]}
            for t in CONSENT_TEXTS
        ],
        "documents": docs,
        "required_documents": required_documents_view(product, docs),
        "warnings": warnings_for({f: getattr(app, f) for f in FIELD_LABELS}) if app.status == Status.DRAFT else [],
        "info_request": info_request_view(session, app, ctx.open_info_request, staff=False),
        "decision": None,
        "offer": offer_view(ctx) if app.status in (Status.OFFER_PENDING, Status.OFFER_ACCEPTED, Status.SIGNING, Status.SIGNED, Status.ISSUED, Status.OFFER_DECLINED, Status.OFFER_EXPIRED, Status.PROCESSING_ERROR) else None,
        "final_terms": None if app.final_amount is None else {
            "product_code": app.final_product_code, "amount": str(app.final_amount), "term_months": app.final_term_months,
            "rate_percent": str(app.final_rate_percent), "monthly_payment": str(app.final_monthly_payment), "option_id": str(app.final_option_id) if app.final_option_id else None,
        },
        "signing": signing_view(ctx) if app.status in (Status.SIGNING, Status.SIGNED, Status.ISSUED) else None,
        "loan": loan_view(session, app),
        "timeline": client_timeline(ctx),
        "notifications": [
            {"id": str(n.id), "code": n.code, "title": n.title, "body": n.body, "created_at": iso(n.created_at), "read": n.read_at is not None}
            for n in session.execute(
                select(Notification).where(Notification.application_id == app.id, Notification.user_id == actor.user_id).order_by(Notification.created_at.desc()).limit(20)
            ).scalars()
        ],
        "created_at": iso(app.created_at),
        "updated_at": iso(app.updated_at),
        "submitted_at": iso(app.submitted_at),
    }
    if app.status == Status.DECLINED and ctx.final_decision is not None:
        view["decision"] = {"outcome": "DECLINED", "reasons": client_reasons(ctx.final_decision.reason_codes, ctx.final_decision.reason_details)}
    return view


def client_list_item(session: Session, app: Application) -> dict[str, Any]:
    ctx = AppContext(session, app)
    cs, step, _ = client_status_of(ctx)
    pol = get_registry().policy_content()
    return {
        "id": str(app.id),
        "application_number": app.application_number,
        "product_code": app.product_code,
        "product_name": pol["products"][app.product_code]["name"],
        "amount": money_str(app.amount),
        "term_months": app.term_months,
        "company_short_name": app.company_short_name,
        "client_status": cs.value,
        "client_status_title": CLIENT_STATUS_TEXTS[{"DECISION_READY": "DECISION_READY_APPROVED"}.get(cs.value, cs.value)]["title"] if cs != ClientStatus.DECISION_READY else "Решение готово",
        "progress_step": step,
        "next_action_label": NEXT_ACTION_LABELS.get(cs, "Открыть"),
        "updated_at": iso(app.updated_at),
        "version": app.version,
    }


# ---------------------------------------------------------------- employee views


def user_names(session: Session, ids: set) -> dict[Any, str]:
    ids = {i for i in ids if i}
    if not ids:
        return {}
    return {u.id: u.full_name for u in session.execute(select(User).where(User.id.in_(ids))).scalars()}


def staff_list_item(session: Session, app: Application, names: dict[Any, str]) -> dict[str, Any]:
    now = utcnow()
    codes = app.manual_review_reasons or []
    reasons = employee_reasons(codes, {}) if codes else []
    return {
        "id": str(app.id),
        "application_number": app.application_number,
        "company_short_name": app.company_short_name,
        "applicant_inn": app.applicant_inn,
        "product_code": app.product_code,
        "amount": money_str(app.amount),
        "term_months": app.term_months,
        "status": app.status,
        "manual_review_reasons": [{"code": r["code"], "text": r["employee_text"]} for r in reasons],
        "grade": app.grade,
        "score": app.score,
        "queued_at": iso(app.review_queued_at),
        "time_in_queue_sec": int((now - app.review_queued_at).total_seconds()) if app.review_queued_at and app.status in (Status.MANUAL_REVIEW, Status.IN_REVIEW, Status.PENDING_RISK_APPROVAL) else None,
        "review_due_at": iso(app.review_due_at),
        "sla_breached": app.sla_breached or (app.review_due_at is not None and app.review_due_at < now and app.status in (Status.MANUAL_REVIEW, Status.IN_REVIEW)),
        "assignee": {"id": str(app.assignee_id), "full_name": names.get(app.assignee_id)} if app.assignee_id else None,
        "failed_stage": app.failed_stage,
        "last_error_code": app.last_error_code,
        "next_retry_at": iso(app.next_retry_at),
        "is_history": app.is_history,
        "submitted_at": iso(app.submitted_at),
        "updated_at": iso(app.updated_at),
        "version": app.version,
    }


def _decision_view(d: Decision, names: dict[Any, str], context: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(d.id),
        "outcome": d.outcome,
        "mode": d.mode,
        "status": d.status,
        "reasons": employee_reasons(d.reason_codes, d.reason_details, context),
        "reason_codes": d.reason_codes,
        "reason_details": d.reason_details,
        "rules_path": d.rules_path,
        "values": d.values,
        "recommendation": d.recommendation,
        "proposed_options": d.proposed_options,
        "override": d.override,
        "four_eyes_trigger": d.four_eyes_trigger,
        "comment": d.comment,
        "proposed_by": names.get(d.proposed_by),
        "decided_by": names.get(d.decided_by),
        "confirmed_by": names.get(d.confirmed_by),
        "scorecard_version": d.scorecard_version,
        "policy_version": d.policy_version,
        "policy_sha256": d.policy_sha256,
        "grade": d.grade,
        "created_at": iso(d.created_at),
    }


def discrepancies(app: Application, decision: Decision | None) -> list[dict[str, Any]]:
    out = []
    if decision is not None and decision.values and decision.values.get("revenue_mismatch") is not None:
        mismatch = Decimal(decision.values["revenue_mismatch"])
        if abs(mismatch) >= Decimal("0.01"):
            source = {"BANK_TURNOVER": "оборотов по счету", "FINANCIAL_STATEMENTS": "данных ГИР БО"}.get(decision.values.get("income_source"), "данных источников")
            pct = (abs(mismatch) * 100).quantize(Decimal("0.01"))
            direction = "выше" if mismatch > 0 else "ниже"
            out.append({"code": "REVENUE_MISMATCH", "value": str(mismatch), "text": f"Выручка в анкете на {pct}% {direction} {source}"})
    if app.existing_monthly_payments_declared is not None and decision is not None and decision.values:
        declared = app.existing_monthly_payments_declared
        existing = Decimal(decision.values["existing_payments"])
        if existing > declared:
            out.append({"code": "PAYMENTS_MISMATCH", "value": str(existing - declared), "text": f"Платежи по данным БКИ на {fmt_money(existing - declared)} больше указанных в анкете"})
    return out


def staff_application_view(session: Session, app: Application, actor: Actor) -> dict[str, Any]:
    pol = get_registry().policy_content()
    product = pol["products"][app.product_code]
    ctx = AppContext(session, app)
    cs, step, key = client_status_of(ctx)
    gctx = guard_context(session, app, actor)
    decisions = list(session.execute(select(Decision).where(Decision.application_id == app.id).order_by(Decision.created_at)).scalars())
    scoring = session.execute(select(ScoringResult).where(ScoringResult.application_id == app.id).order_by(ScoringResult.calculated_at.desc()).limit(1)).scalar_one_or_none()
    comments = list(session.execute(select(Comment).where(Comment.application_id == app.id).order_by(Comment.created_at)).scalars())
    snapshots = list(session.execute(select(SourceSnapshot).where(SourceSnapshot.application_id == app.id).order_by(SourceSnapshot.requested_at)).scalars())
    events = list(session.execute(select(Event).where(Event.application_id == app.id).order_by(Event.seq)).scalars())
    info_requests = list(session.execute(select(InfoRequest).where(InfoRequest.application_id == app.id).order_by(InfoRequest.created_at)).scalars())
    changes = list(session.execute(select(FieldChange).where(FieldChange.application_id == app.id).order_by(FieldChange.changed_at)).scalars())
    ids = {app.assignee_id, app.client_user_id} | {c.author_id for c in comments} | {e.actor_id for e in events}
    for d in decisions:
        ids |= {d.proposed_by, d.decided_by, d.confirmed_by}
    names = user_names(session, ids)
    reason_ctx = {"inn": app.applicant_inn, "assignee": names.get(app.assignee_id), "amount": money_str(app.amount)}
    latest_policy_decision = next((d for d in reversed(decisions) if d.mode == "AUTO"), None)
    sources: dict[str, Any] = {}
    for sn in snapshots:
        entry = sources.setdefault(sn.source, {"source": sn.source, "attempts": [], "latest": None})
        entry["attempts"].append(
            {"attempt": sn.attempt, "stage": sn.stage, "outcome": sn.outcome, "error_code": sn.error_code, "requested_at": iso(sn.requested_at), "duration_ms": sn.duration_ms, "external_request_id": sn.external_request_id}
        )
        if sn.outcome in ("SUCCESS", "NO_DATA"):
            entry["latest"] = {"outcome": sn.outcome, "received_at": iso(sn.responded_at), "data": sn.response}
    consents = consent_rows(session, app)
    audit_rows = []
    if actor.type == ActorType.RISK_MANAGER:
        audit_rows = [
            {"occurred_at": iso(a.occurred_at), "actor_login": a.actor_login, "actor_role": a.actor_role, "action": a.action, "result": a.result, "ip_address": a.ip_address, "details": a.details}
            for a in session.execute(select(AuditLog).where(AuditLog.application_id == app.id).order_by(AuditLog.id)).scalars()
        ]
    return {
        "id": str(app.id),
        "application_number": app.application_number,
        "version": app.version,
        "status": app.status,
        "client_status": cs.value,
        "client_status_title": status_text(ctx, key, product=product, consents_ok=True)["title"],
        "is_history": app.is_history,
        "available_actions": available_actions(app.status, gctx, app.is_history),
        "product_code": app.product_code,
        "product_name": product["name"],
        "purpose": app.purpose,
        "purpose_title": PURPOSES[app.purpose]["title"],
        "applicant_inn": app.applicant_inn,
        "applicant_type": app.applicant_type,
        "company_short_name": app.company_short_name,
        "client": {"id": str(app.client_user_id), "full_name": names.get(app.client_user_id), "representative_role": app.representative_role},
        "form": form_view(app),
        "company": registry_view(app),
        "submitted_snapshot": app.submitted_snapshot,
        "field_changes": [
            {"field_name": c.field_name, "field_label": FIELD_LABELS.get(c.field_name), "old_value": c.old_value, "new_value": c.new_value, "changed_at": iso(c.changed_at), "info_request_id": str(c.info_request_id) if c.info_request_id else None}
            for c in changes
        ],
        "assignee": {"id": str(app.assignee_id), "full_name": names.get(app.assignee_id)} if app.assignee_id else None,
        "sla": {"queued_at": iso(app.review_queued_at), "review_due_at": iso(app.review_due_at), "sla_breached": app.sla_breached},
        "processing": {
            "failed_stage": app.failed_stage, "last_error_code": app.last_error_code, "enrichment_retry_count": app.enrichment_retry_count,
            "next_retry_at": iso(app.next_retry_at), "auto_info_request_count": app.auto_info_request_count, "info_request_count": app.info_request_count,
            "manual_review_required": app.manual_review_required,
            "technical_reason": employee_reasons(["TECH_SOURCE_UNAVAILABLE" if app.failed_stage == "ENRICHMENT" else "TECH_PROCESSING_FAILED"], {}, {"failed_stage": app.failed_stage, "last_error_code": app.last_error_code, "source": "БКИ/реестры"})[0] if app.status == Status.PROCESSING_ERROR else None,
        },
        "manual_review_reasons": employee_reasons(app.manual_review_reasons or [], latest_policy_decision.reason_details if latest_policy_decision else {}, reason_ctx),
        "discrepancies": discrepancies(app, latest_policy_decision),
        "scoring": None if scoring is None else {
            "score": scoring.score, "grade": scoring.grade, "pd": str(scoring.pd), "factor_contributions": scoring.factor_contributions,
            "features": scoring.features, "scorecard_version": scoring.scorecard_version, "scorecard_sha256": scoring.scorecard_sha256,
            "as_of_date": scoring.as_of_date.isoformat(), "calculated_at": iso(scoring.calculated_at),
        },
        "decisions": [_decision_view(d, names, reason_ctx) for d in decisions],
        "sources": list(sources.values()),
        "offer": offer_view(ctx),
        "final_terms": None if app.final_amount is None else {"product_code": app.final_product_code, "amount": str(app.final_amount), "term_months": app.final_term_months, "rate_percent": str(app.final_rate_percent), "monthly_payment": str(app.final_monthly_payment)},
        "signing": signing_view(ctx),
        "loan": loan_view(session, app),
        "documents": documents_view(session, app),
        "required_documents": required_documents_view(product, documents_view(session, app)),
        "consents": [
            {"consent_type": c.consent_type, "text_version": c.text_version, "text_sha256": c.text_sha256, "granted_at": iso(c.granted_at), "expires_at": iso(c.expires_at), "revoked_at": iso(c.revoked_at), "ip_address": c.ip_address, "user_agent": c.user_agent}
            for c in consents
        ],
        "info_requests": [info_request_view(session, app, ir, staff=True) for ir in info_requests],
        "comments": [{"id": str(c.id), "kind": c.kind, "author": names.get(c.author_id), "body": c.body, "created_at": iso(c.created_at)} for c in comments],
        "history": [
            {"event_id": str(e.event_id), "event_type": e.event_type, "occurred_at": iso(e.occurred_at), "actor_type": e.actor_type, "actor": names.get(e.actor_id), "application_version": e.application_version, "payload": e.payload}
            for e in events
        ],
        "audit": audit_rows,
        "created_at": iso(app.created_at),
        "submitted_at": iso(app.submitted_at),
        "decided_at": iso(app.decided_at),
        "issued_at": iso(app.issued_at),
        "updated_at": iso(app.updated_at),
    }


