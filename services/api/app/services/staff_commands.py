"""Employee commands: take, release, approve, counter offer, request info, decline, four eyes, retry, comment."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..domain.configs import get_registry
from ..domain.dictionaries import (
    DOCUMENT_TYPES,
    EXTRA_REASON_CODES,
    INFO_REQUEST_FIELDS,
    MANUAL_DECLINE_CODES,
    UNDERWRITER_INFO_CODES,
    fmt_dt,
    fmt_money,
    plural_ru,
    render,
)
from ..domain.money import dec, max_amount_for_payment, money
from ..domain.policy import build_option, rate_for
from ..domain.validation import normalize
from ..enums import STAGE_JOB, Command, Outcome, Role, Status
from ..errors import (
    ApiError,
    Conflict,
    ValidationFailed,
    invalid_transition,
    version_conflict,
)
from ..models import (
    Application,
    Comment,
    Decision,
    InfoRequest,
    InfoRequestItem,
    Offer,
    OfferOption,
    ScoringResult,
    User,
)
from .core import (
    Actor,
    apply_transition,
    audit,
    due,
    emit,
    enqueue,
    guard_context,
    notify,
    notify_role,
    utcnow,
)
from .params import process_params


def _comment(session: Session, app: Application, actor: Actor, body: str | None, kind: str, *, required: bool = True) -> Comment | None:
    text = (body or "").strip()
    if not text:
        if required:
            raise ValidationFailed(fields=[{"field": "comment", "code": "REQUIRED", "message": "Комментарий обязателен"}])
        return None
    if len(text) > 4000:
        raise ValidationFailed(fields=[{"field": "comment", "code": "INVALID_FORMAT", "message": "Комментарий не длиннее 4000 символов"}])
    c = Comment(id=uuid.uuid4(), application_id=app.id, author_id=actor.user_id, kind=kind, body=text, created_at=utcnow())
    session.add(c)
    session.flush()
    return c


def _latest_scoring(session: Session, app: Application) -> ScoringResult | None:
    return session.execute(select(ScoringResult).where(ScoringResult.application_id == app.id).order_by(ScoringResult.calculated_at.desc()).limit(1)).scalar_one_or_none()


def _latest_policy_decision(session: Session, app: Application) -> Decision | None:
    return session.execute(select(Decision).where(Decision.application_id == app.id, Decision.mode == "AUTO").order_by(Decision.created_at.desc()).limit(1)).scalar_one_or_none()


def decision_made_payload(app: Application, d: Decision, options: list[dict[str, Any]]) -> dict[str, Any]:
    amounts = [Decimal(o["amount"]) for o in options]
    return {
        "decision_id": str(d.id), "outcome": d.outcome, "mode": d.mode, "reason_codes": d.reason_codes,
        "policy_version": d.policy_version, "scorecard_version": d.scorecard_version, "grade": d.grade, "override": d.override,
        "requested_amount": str(app.amount) if app.amount is not None else None,
        "offered_amount_max": str(max(amounts)) if amounts else None,
        "offered_term_months": max((o["term_months"] for o in options), default=None),
        "options_count": len(options),
        "time_from_submit_sec": int((utcnow() - app.submitted_at).total_seconds()) if app.submitted_at else None,
    }


def create_offer(session: Session, app: Application, decision: Decision, options: list[dict[str, Any]], actor: Actor) -> Offer:
    params = process_params()
    offer = Offer(id=uuid.uuid4(), application_id=app.id, decision_id=decision.id, outcome=decision.outcome, status="ACTIVE", expires_at=due(params.offer_ttl_seconds), created_at=utcnow())
    session.add(offer)
    for i, o in enumerate(options):
        session.add(
            OfferOption(
                id=uuid.uuid4(), offer_id=offer.id, position=i, option_type=o["option_type"], product_code=o["product_code"], amount=Decimal(o["amount"]),
                term_months=o["term_months"], rate_percent=Decimal(o["rate_percent"]), monthly_payment=Decimal(o["monthly_payment"]),
                total_payment=Decimal(o["total_payment"]), overpayment=Decimal(o["overpayment"]), requires_owner_guarantee=o["requires_owner_guarantee"],
                requires_collateral=o["requires_collateral"], tranche_max_term_months=o.get("tranche_max_term_months"), recommended=bool(o.get("recommended")),
            )
        )
    session.flush()
    emit(session, "OFFER_ISSUED", actor, application=app, payload={
        "offer_id": str(offer.id), "expires_at": offer.expires_at.isoformat(),
        "options": [{k: o[k] for k in ("option_type", "product_code", "amount", "term_months", "rate_percent", "monthly_payment")} for o in options],
    })
    code = "NTF_DECISION_APPROVED" if decision.outcome == Outcome.APPROVED else "NTF_DECISION_COUNTER_OFFER"
    first = options[0]
    notify(session, app.client_user_id, code, application=app, amount=fmt_money(first["amount"]), term=first["term_months"], expires_at=fmt_dt(offer.expires_at))
    return offer


# Take and release


def take(session: Session, actor: Actor, app: Application, *, expected_version: int) -> Application:
    queued_at = app.review_queued_at
    try:
        apply_transition(session, app, "T-25", actor, trigger=Command.TAKE, expected_version=expected_version, changes={"assignee_id": actor.user_id})
    except ApiError as exc:
        if exc.status == 409 and app.assignee_id and app.assignee_id != actor.user_id:
            name = session.execute(select(User.full_name).where(User.id == app.assignee_id)).scalar_one_or_none()
            raise Conflict(f"Заявку уже взял {name}", code="ALREADY_TAKEN", details={"assignee": name}) from exc
        raise
    emit(session, "REVIEW_TAKEN", actor, application=app, payload={"assignee_id": str(actor.user_id), "wait_sec": int((utcnow() - queued_at).total_seconds()) if queued_at else None})
    notify(session, app.client_user_id, "NTF_REVIEW_STARTED", application=app, review_due_at=fmt_dt(app.review_due_at))
    return app


def release(session: Session, actor: Actor, app: Application, *, expected_version: int, comment: str | None) -> Application:
    c = _comment(session, app, actor, comment, "RELEASE")
    apply_transition(session, app, "T-26", actor, trigger=Command.RELEASE, expected_version=expected_version, changes={"assignee_id": None})
    emit(session, "REVIEW_RELEASED", actor, application=app, payload={"assignee_id": str(actor.user_id), "comment_id": str(c.id)})
    return app


# Positive decisions


def _manual_options(app: Application, grade: str, raw: list[dict[str, Any]], recommendation: dict[str, Any] | None) -> list[dict[str, Any]]:
    pol = get_registry().policy_content()
    if not 1 <= len(raw) <= pol["counter_offer"]["max_counter_options"]:
        raise ValidationFailed(fields=[{"field": "options", "code": "OUT_OF_RANGE", "message": "Задайте от 1 до 3 вариантов"}])
    rec_options = (recommendation or {}).get("options") or []
    line_code = pol["counter_offer"]["credit_line_product"]
    out = []
    errors = []
    for i, o in enumerate(raw):
        code = o.get("product_code") or app.product_code
        allowed_products = {app.product_code}
        if app.product_code in pol["counter_offer"]["credit_line_source_products"]:
            allowed_products.add(line_code)
        if code not in allowed_products:
            errors.append({"field": f"options.{i}.product_code", "code": "INVALID_FORMAT", "message": "Можно предложить исходный продукт или кредитную линию"})
            continue
        product = pol["products"][code]
        try:
            amount, amount_error = normalize("amount", o.get("amount"))
            if amount_error or amount is None:
                raise ValueError
            term = int(o.get("term_months"))
        except (ArithmeticError, TypeError, ValueError):
            errors.append({"field": f"options.{i}", "code": "INVALID_FORMAT", "message": "Укажите сумму и срок"})
            continue
        if not dec(product["amount_min"]) <= amount <= dec(product["amount_max"]) or amount % dec(product["amount_step"]) != 0:
            errors.append({"field": f"options.{i}.amount", "code": "OUT_OF_RANGE", "message": f"Сумма от {fmt_money(product['amount_min'])} до {fmt_money(product['amount_max'])}, кратно {fmt_money(product['amount_step'])}"})
            continue
        if not product["term_min_months"] <= term <= product["term_max_months"]:
            errors.append({"field": f"options.{i}.term_months", "code": "OUT_OF_RANGE", "message": f"Срок от {product['term_min_months']} до {product['term_max_months']} мес."})
            continue
        rate = rate_for(pol, code, grade)
        tranche = product.get("tranche_max_term_months")
        match = next((r for r in rec_options if r["product_code"] == code and Decimal(r["amount"]) == amount and r["term_months"] == term), None)
        option_type = match["option_type"] if match else ("REQUESTED" if code == app.product_code and amount == app.amount and term == app.term_months else "UNDERWRITER_TERMS")
        out.append(build_option(pol, option_type, code, amount, term, rate, app.applicant_type, i == 0, payment_term=tranche))
    if errors:
        raise ValidationFailed(fields=errors)
    return out


def _override(app: Application, grade: str, options: list[dict[str, Any]], policy_decision: Decision | None) -> bool:
    pol = get_registry().policy_content()
    if grade in pol["products"][app.product_code]["decline_grades"]:
        return True
    values = (policy_decision.values if policy_decision else None) or {}
    if "allowed_payment" not in values:
        return False
    allowed = dec(values["allowed_payment"])
    for o in options:
        product = pol["products"][o["product_code"]]
        term = product.get("tranche_max_term_months") or o["term_months"]
        max_amount = max_amount_for_payment(allowed, o["rate_percent"], term, product["amount_max"], pol["counter_offer"]["amount_rounding"])
        if dec(o["amount"]) > max_amount:
            return True
    return False


def decide_positive(session: Session, actor: Actor, app: Application, *, command: str, expected_version: int, comment: str | None, options: list[dict[str, Any]] | None) -> Application:
    if app.status != Status.IN_REVIEW:
        raise invalid_transition(app.status, None, internal=True)
    gctx = guard_context(session, app, actor)
    if gctx.assignee_id != actor.user_id:
        raise ApiError("Решение может принять только исполнитель заявки", code="NOT_ASSIGNEE", status=403)
    if expected_version != app.version:
        raise version_conflict(app.version)
    scoring = _latest_scoring(session, app)
    if scoring is None:
        raise Conflict("Нельзя одобрить заявку без результата скоринга", code="SCORING_REQUIRED")
    policy_decision = _latest_policy_decision(session, app)
    recommendation = policy_decision.recommendation if policy_decision else None
    raw = [{"product_code": app.product_code, "amount": str(app.amount), "term_months": app.term_months}] if command == Command.APPROVE else (options or [])
    built = _manual_options(app, scoring.grade, raw, recommendation)
    if command == Command.APPROVE:
        built[0]["option_type"] = "REQUESTED"
    params = process_params()
    override = _override(app, scoring.grade, built, policy_decision)
    trigger = None
    if any(dec(o["amount"]) > dec(params.underwriter_authority_limit) for o in built):
        trigger = "AUTHORITY_LIMIT"
    elif override and params.override_requires_risk_approval:
        trigger = "OVERRIDE"
    outcome = Outcome.APPROVED if command == Command.APPROVE else Outcome.COUNTER_OFFER
    codes = [] if outcome == Outcome.APPROVED else ["CO_UNDERWRITER_TERMS"]
    if any(o["product_code"] == "CREDIT_LINE" for o in built):
        codes.append("CO_PRODUCT_ALTERNATIVE")
    c = _comment(session, app, actor, comment, "DECISION")
    pol = get_registry().policy
    decision = Decision(
        id=uuid.uuid4(), application_id=app.id, scoring_result_id=scoring.id, outcome=outcome.value, mode="MANUAL",
        status="PROPOSED" if trigger else "FINAL", reason_codes=codes, reason_details={}, rules_path=[], values=policy_decision.values if policy_decision else None,
        recommendation=recommendation, proposed_options=built, override=override, four_eyes_trigger=trigger, comment=c.body,
        proposed_by=actor.user_id, decided_by=None if trigger else actor.user_id, scorecard_version=scoring.scorecard_version,
        policy_version=pol.version, policy_sha256=pol.sha256, grade=scoring.grade, created_at=utcnow(),
    )
    session.add(decision)
    session.flush()
    if trigger:
        apply_transition(session, app, "T-28", actor, trigger=command, expected_version=expected_version, ctx=gctx)
        emit(session, "FOUR_EYES_REQUESTED", actor, application=app, payload={"decision_id": str(decision.id), "proposed_by": str(actor.user_id), "confirmed_by": None, "trigger": trigger})
        notify_role(session, Role.RISK_MANAGER, "NTF_EMP_APPROVAL_REQUESTED", application=app, amount=fmt_money(max(dec(o["amount"]) for o in built)))
        return app
    apply_transition(session, app, "T-27", actor, trigger=command, expected_version=expected_version, ctx=gctx, changes={"decided_at": utcnow()})
    emit(session, "DECISION_MADE", actor, application=app, payload=decision_made_payload(app, decision, built))
    offer = create_offer(session, app, decision, built, actor)
    app.current_offer_id = offer.id
    return app


def confirm_decision(session: Session, actor: Actor, app: Application, *, expected_version: int, comment: str | None) -> Application:
    proposal = session.execute(select(Decision).where(Decision.application_id == app.id, Decision.status == "PROPOSED").order_by(Decision.created_at.desc()).limit(1)).scalar_one_or_none()
    if proposal is None:
        raise invalid_transition(app.status, None, internal=True)
    c = _comment(session, app, actor, comment, "DECISION", required=False)
    apply_transition(session, app, "T-31", actor, trigger=Command.CONFIRM_DECISION, expected_version=expected_version, changes={"decided_at": utcnow()})
    proposal.status, proposal.confirmed_by, proposal.decided_by = "FINAL", actor.user_id, proposal.proposed_by
    session.flush()
    emit(session, "FOUR_EYES_APPROVED", actor, application=app, payload={"decision_id": str(proposal.id), "proposed_by": str(proposal.proposed_by), "confirmed_by": str(actor.user_id), "trigger": proposal.four_eyes_trigger, "comment_id": str(c.id) if c else None})
    emit(session, "DECISION_MADE", actor, application=app, payload=decision_made_payload(app, proposal, proposal.proposed_options or []))
    offer = create_offer(session, app, proposal, proposal.proposed_options or [], actor)
    app.current_offer_id = offer.id
    return app


def return_decision(session: Session, actor: Actor, app: Application, *, expected_version: int, comment: str | None) -> Application:
    c = _comment(session, app, actor, comment, "RETURN")
    proposal = session.execute(select(Decision).where(Decision.application_id == app.id, Decision.status == "PROPOSED").order_by(Decision.created_at.desc()).limit(1)).scalar_one_or_none()
    apply_transition(session, app, "T-32", actor, trigger=Command.RETURN_DECISION, expected_version=expected_version)
    if proposal is not None:
        proposal.status = "REJECTED"
        emit(session, "FOUR_EYES_REJECTED", actor, application=app, payload={"decision_id": str(proposal.id), "proposed_by": str(proposal.proposed_by), "confirmed_by": str(actor.user_id), "trigger": proposal.four_eyes_trigger, "comment_id": str(c.id)})
        notify(session, proposal.proposed_by, "NTF_EMP_DECISION_RETURNED", application=app, comment_preview=c.body[:120])
    return app


# Info request and decline


def build_info_items(app: Application, raw_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not 1 <= len(raw_items) <= 10:
        raise ValidationFailed(fields=[{"field": "items", "code": "OUT_OF_RANGE", "message": "Добавьте от 1 до 10 пунктов"}])
    dictionary = {**get_registry().policy_content()["reason_codes"], **EXTRA_REASON_CODES}
    items, errors = [], []
    for i, it in enumerate(raw_items):
        code = it.get("reason_code")
        answer_type = it.get("answer_type")
        if code not in UNDERWRITER_INFO_CODES:
            errors.append({"field": f"items.{i}.reason_code", "code": "INVALID_FORMAT", "message": "Выберите код причины NI_*"})
            continue
        if answer_type not in ("DOCUMENT", "FIELD", "TEXT"):
            errors.append({"field": f"items.{i}.answer_type", "code": "INVALID_FORMAT", "message": "Тип ответа: документ, поле или текст"})
            continue
        field_name = it.get("field_name") if answer_type == "FIELD" else None
        if answer_type == "FIELD" and field_name not in INFO_REQUEST_FIELDS:
            errors.append({"field": f"items.{i}.field_name", "code": "INVALID_FORMAT", "message": "Это поле нельзя запросить у клиента"})
            continue
        document_type = it.get("document_type") if answer_type == "DOCUMENT" else None
        if answer_type == "DOCUMENT" and document_type not in DOCUMENT_TYPES:
            errors.append({"field": f"items.{i}.document_type", "code": "INVALID_FORMAT", "message": "Выберите тип документа"})
            continue
        custom = (it.get("client_text") or "").strip()
        if len(custom) > 1000:
            errors.append({"field": f"items.{i}.client_text", "code": "INVALID_FORMAT", "message": "Текст не длиннее 1000 символов"})
            continue
        doc = DOCUMENT_TYPES.get(document_type or "", {})
        template = dictionary[code]["client_text"]
        default_text = render(template, {"document_name": doc.get("title"), "document_purpose": doc.get("purpose"), "question_text": custom or None})
        if code == "NI_OTHER" and not custom:
            errors.append({"field": f"items.{i}.client_text", "code": "REQUIRED", "message": "Сформулируйте вопрос для клиента"})
            continue
        items.append({
            "reason_code": code, "answer_type": answer_type, "field_name": field_name, "document_type": document_type,
            "client_text": custom or default_text, "employee_text": render(dictionary[code]["employee_text"], {"document_type": document_type}),
            "required": bool(it.get("required", True)),
        })
    if errors:
        raise ValidationFailed(fields=errors)
    return items


def create_info_request(session: Session, app: Application, actor: Actor, *, source: str, items: list[dict[str, Any]], decision_id: uuid.UUID | None) -> InfoRequest:
    params = process_params()
    ir = InfoRequest(id=uuid.uuid4(), application_id=app.id, decision_id=decision_id, source=source, status="OPEN", cycle_number=app.info_request_count, created_by=actor.user_id, created_at=utcnow(), due_at=due(params.info_request_ttl_seconds))
    session.add(ir)
    session.flush()
    for i, it in enumerate(items):
        session.add(InfoRequestItem(id=uuid.uuid4(), info_request_id=ir.id, position=i, **it))
    emit(session, "INFO_REQUESTED", actor, application=app, payload={"info_request_id": str(ir.id), "source": source, "items": [{"reason_code": it["reason_code"], "answer_type": it["answer_type"]} for it in items], "due_at": ir.due_at.isoformat(), "cycle_number": ir.cycle_number})
    notify(session, app.client_user_id, "NTF_INFO_REQUESTED", application=app, k=len(items), k_text=plural_ru(len(items), "вопрос", "вопроса", "вопросов"), due_at=fmt_dt(ir.due_at))
    return ir


def request_info(session: Session, actor: Actor, app: Application, *, expected_version: int, items: list[dict[str, Any]], comment: str | None) -> Application:
    built = build_info_items(app, items)
    c = _comment(session, app, actor, comment, "DECISION")
    scoring = _latest_scoring(session, app)
    pol = get_registry().policy
    decision = Decision(
        id=uuid.uuid4(), application_id=app.id, scoring_result_id=scoring.id if scoring else None, outcome="NEEDS_INFO", mode="MANUAL", status="FINAL",
        reason_codes=sorted({i["reason_code"] for i in built}), reason_details={}, rules_path=[], comment=c.body, proposed_by=actor.user_id,
        decided_by=actor.user_id, scorecard_version=scoring.scorecard_version if scoring else None, policy_version=pol.version, policy_sha256=pol.sha256,
        grade=scoring.grade if scoring else None, created_at=utcnow(),
    )
    session.add(decision)
    session.flush()
    apply_transition(session, app, "T-29", actor, trigger=Command.REQUEST_INFO, expected_version=expected_version, changes={"info_request_count": app.info_request_count + 1})
    emit(session, "DECISION_MADE", actor, application=app, payload=decision_made_payload(app, decision, []))
    create_info_request(session, app, actor, source="UNDERWRITER", items=built, decision_id=decision.id)
    return app


def decline(session: Session, actor: Actor, app: Application, *, expected_version: int, reason_codes: list[str], comment: str | None) -> Application:
    codes = list(dict.fromkeys(reason_codes or []))
    if not codes or any(c not in MANUAL_DECLINE_CODES for c in codes):
        raise ValidationFailed(fields=[{"field": "reason_codes", "code": "INVALID_FORMAT", "message": "Выберите хотя бы одну причину отказа из SF_* и DCL_* (кроме DCL_AFFORDABILITY)"}])
    c = _comment(session, app, actor, comment, "DECISION")
    scoring = _latest_scoring(session, app)
    policy_decision = _latest_policy_decision(session, app)
    details = {k: v for k, v in ((policy_decision.reason_details if policy_decision else {}) or {}).items() if k in codes}
    pol = get_registry().policy
    decision = Decision(
        id=uuid.uuid4(), application_id=app.id, scoring_result_id=scoring.id if scoring else None, outcome="DECLINED", mode="MANUAL", status="FINAL",
        reason_codes=codes, reason_details=details, rules_path=[], values=policy_decision.values if policy_decision else None,
        recommendation=policy_decision.recommendation if policy_decision else None, comment=c.body, proposed_by=actor.user_id, decided_by=actor.user_id,
        scorecard_version=scoring.scorecard_version if scoring else None, policy_version=pol.version, policy_sha256=pol.sha256,
        grade=scoring.grade if scoring else None, created_at=utcnow(),
    )
    session.add(decision)
    session.flush()
    apply_transition(session, app, "T-30", actor, trigger=Command.DECLINE, expected_version=expected_version, changes={"decided_at": utcnow()})
    emit(session, "DECISION_MADE", actor, application=app, payload=decision_made_payload(app, decision, []))
    notify(session, app.client_user_id, "NTF_DECISION_DECLINED", application=app)
    return app


# Technical operations


def retry_processing(session: Session, actor: Actor, app: Application, *, expected_version: int) -> Application:
    failed_stage = app.failed_stage
    apply_transition(
        session, app, "T-44", actor, trigger=Command.RETRY_PROCESSING, expected_version=expected_version,
        changes={"enrichment_retry_count": 0, "next_retry_at": None, "failed_stage": None, "last_error_code": None},
    )
    enqueue(session, STAGE_JOB[Status(app.status)], app, correlation_id=actor.correlation_id)
    emit(session, "PROCESSING_RETRIED", actor, application=app, payload={"failed_stage": failed_stage})
    return app


def add_comment(session: Session, actor: Actor, app: Application, body: str | None) -> Comment:
    if app.status == Status.DRAFT:
        raise invalid_transition(app.status, None, internal=True)
    c = _comment(session, app, actor, body, "INTERNAL")
    emit(session, "COMMENT_ADDED", actor, application=app, payload={"comment_id": str(c.id)})
    audit(session, actor, Command.ADD_COMMENT.value, application_id=app.id, object_type="comment", object_id=str(c.id))
    return c

