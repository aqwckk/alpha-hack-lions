"""Public reference data, product selection by task, payment calculator, wizard analytics events."""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..db import get_db
from ..domain import catalog as catalog_domain
from ..domain.configs import get_registry
from ..domain.dictionaries import (
    CONSENT_TEXTS,
    DOCUMENT_TYPES,
    OFFER_DECLINE_REASONS,
    PRODUCT_TEXTS,
    PURPOSES,
    consent_text_sha256,
    today_msk,
)
from ..domain.inn import inn_error
from ..domain.money import add_months, money, months_between, payment_schedule, totals
from ..errors import ValidationFailed
from ..schemas import (
    AnalyticsEventRequest,
    CalculateRequest,
    MatchRequest,
    MatchResponse,
    ScheduleResponse,
)
from ..services import integrations
from ..services.core import Actor, emit
from .deps import client_actor, current_actor

router = APIRouter(prefix="/api/v1", tags=["catalog"])


def _amount(value: Any, field: str = "amount") -> Decimal:
    try:
        d = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValidationFailed(fields=[{"field": field, "code": "INVALID_FORMAT", "message": "Укажите сумму в рублях"}]) from exc
    if not d.is_finite() or d <= 0 or d > Decimal("10000000000") or d != d.to_integral_value():
        raise ValidationFailed(fields=[{"field": field, "code": "INVALID_FORMAT", "message": "Укажите положительную сумму в целых рублях"}])
    return money(d)


def _rate(value: str) -> Decimal:
    try:
        rate = Decimal(value)
        if not rate.is_finite() or not Decimal("0") <= rate <= Decimal("100") or rate != money(rate):
            raise ValueError
        return money(rate)
    except (ArithmeticError, ValueError, TypeError) as exc:
        raise ValidationFailed(fields=[{"field": "rate_percent", "code": "OUT_OF_RANGE", "message": "Ставка от 0 до 100% годовых, не больше двух знаков после запятой"}]) from exc


@router.get("/catalog/products")
def products() -> dict[str, Any]:
    """Products of the active policy with client texts (CREDIT_LINE has direct_application=false)."""
    pol = get_registry().policy_content()
    items = []
    for code, p in pol["products"].items():
        items.append({
            "product_code": code, "name": p["name"], **PRODUCT_TEXTS[code], "direct_application": p["direct_application"],
            "applicant_types": p["applicant_types"], "allowed_purposes": p["allowed_purposes"], "amount_min": p["amount_min"],
            "amount_max": p["amount_max"], "amount_step": p["amount_step"], "term_min_months": p["term_min_months"],
            "term_max_months": p["term_max_months"], "base_rate_percent": p["base_rate_percent"], "review_mode": p["review_mode"],
            "min_business_age_months": p["min_business_age_months"], "requires_owner_guarantee_for": p["requires_owner_guarantee_for"],
            "requires_collateral": p["requires_collateral"], "required_documents": p["required_documents"],
            "tranche_max_term_months": p.get("tranche_max_term_months"),
            "requirements": catalog_domain.requirements(p, None),
        })
    return {"policy_version": pol["version"], "items": items}


@router.get("/catalog/dictionaries")
def dictionaries() -> dict[str, Any]:
    """Purposes, document types, consent texts and offer decline reasons for the client interface."""
    return {
        "purposes": [{"code": k, **v} for k, v in PURPOSES.items()],
        "document_types": [{"code": k, **v} for k, v in DOCUMENT_TYPES.items()],
        "consents": [
            {"code": k, "title": v["title"], "short_text": v["short_text"], "full_text": v["full_text"], "text_version": v["version"], "text_sha256": consent_text_sha256(k), "ttl_days": v["ttl_days"], "required": True}
            for k, v in CONSENT_TEXTS.items()
        ],
        "offer_decline_reasons": [{"code": k, "title": v} for k, v in OFFER_DECLINE_REASONS.items()],
        "representative_roles": [
            {"code": "OWNER", "title": "Собственник"}, {"code": "CEO", "title": "Генеральный директор"}, {"code": "CFO", "title": "Финансовый директор"},
            {"code": "ACCOUNTANT", "title": "Бухгалтер"}, {"code": "FINANCE_MANAGER", "title": "Сотрудник, отвечающий за финансирование"},
            {"code": "OTHER_AUTHORIZED", "title": "Иной уполномоченный сотрудник"},
        ],
        "collateral_types": [
            {"code": "EQUIPMENT", "title": "Оборудование"}, {"code": "VEHICLE", "title": "Транспорт"},
            {"code": "REAL_ESTATE", "title": "Недвижимость"}, {"code": "PURCHASED_ASSET", "title": "Приобретаемое имущество"},
        ],
        "collateral_owners": [{"code": "APPLICANT", "title": "Заявителю"}, {"code": "THIRD_PARTY", "title": "Третьему лицу"}],
    }


@router.post("/catalog/match", response_model=MatchResponse)
def match(body: MatchRequest, actor: Actor = Depends(client_actor)) -> dict[str, Any]:
    """Selection by task (product-catalog.md, section 4). With an INN the business age is checked early."""
    if body.purpose not in PURPOSES:
        raise ValidationFailed(fields=[{"field": "purpose", "code": "REQUIRED", "message": "Выберите, на что нужны деньги"}])
    amount = _amount(body.amount)
    age = reg_date = None
    early: dict[str, Any] | None = None
    applicant_type = body.applicant_type
    if body.inn:
        code = inn_error(body.inn)
        if code:
            raise ValidationFailed(fields=[{"field": "inn", "code": code, "message": "Проверьте ИНН"}])
        res = integrations.fetch_source("REGISTRY", body.inn, timeout=3.0, correlation_id=actor.correlation_id)
        if res.outcome == "SUCCESS" and res.data.get("found") and res.data.get("registration_date"):
            reg_date = date.fromisoformat(res.data["registration_date"])
            age = months_between(reg_date, today_msk())
            applicant_type = applicant_type or res.data.get("applicant_type")
            early = {"status": "FOUND", "business_age_months": age}
        elif res.outcome == "SUCCESS":
            early = {"status": "NOT_FOUND"}
        else:
            early = {"status": "SOURCE_UNAVAILABLE"}
    result = catalog_domain.match_products(get_registry().policy_content(), body.purpose, amount, body.term_months, applicant_type, age, reg_date)
    result["early_check"] = early
    return result


@router.post("/catalog/calculate", response_model=ScheduleResponse)
def calculate(body: CalculateRequest, actor: Actor = Depends(current_actor)) -> dict[str, Any]:
    """Annuity payment at the base rate of the product (or the given rate); schedule on request."""
    pol = get_registry().policy_content()
    if body.product_code not in pol["products"]:
        raise ValidationFailed(fields=[{"field": "product_code", "code": "INVALID_FORMAT", "message": "Неизвестный продукт"}])
    amount = _amount(body.amount)
    product = pol["products"][body.product_code]
    if not Decimal(product["amount_min"]) <= amount <= Decimal(product["amount_max"]) or amount % Decimal(product["amount_step"]) != 0:
        raise ValidationFailed(fields=[{"field": "amount", "code": "OUT_OF_RANGE", "message": "Сумма должна соответствовать границам и шагу продукта"}])
    if not product["term_min_months"] <= body.term_months <= product["term_max_months"]:
        raise ValidationFailed(fields=[{"field": "term_months", "code": "OUT_OF_RANGE", "message": "Срок должен соответствовать границам продукта"}])
    rate = _rate(body.rate_percent) if body.rate_percent is not None else money(pol["products"][body.product_code]["base_rate_percent"])
    first = add_months(today_msk(), 1)
    t = totals(amount, rate, body.term_months)
    return {
        "product_code": body.product_code, "amount": str(amount), "term_months": body.term_months, "rate_percent": str(rate),
        "monthly_payment": str(t["monthly_payment"]), "total_payment": str(t["total_payment"]), "overpayment": str(t["overpayment"]),
        "first_payment_date": first.isoformat(), "rows": payment_schedule(amount, rate, body.term_months, first) if body.with_schedule else [],
    }


@router.post("/analytics/events", status_code=202)
def analytics_event(body: AnalyticsEventRequest, actor: Actor = Depends(client_actor), session: Session = Depends(get_db)) -> dict[str, str]:
    """Product analytics events of the wizard (events.md, 2.1); no personal data in the payload."""
    payload: dict[str, Any] = {"wizard_session_id": body.wizard_session_id}
    if body.event_type == "PRODUCT_SELECTED":
        payload.update(product_code=body.product_code, purpose=body.purpose, amount=str(_amount(body.amount)) if body.amount is not None else None, term_months=body.term_months, rank=body.rank, was_recommended=body.was_recommended)
    emit(session, body.event_type, actor, payload=payload)
    session.commit()
    return {"status": "accepted"}
