"""Product selection by the client's task and the payment calculator (product-catalog.md, sections 4-5).

Deterministic, no AI: candidates are direct-application products whose purposes include the task and
whose amount range covers the request; the first candidate in catalog priority is recommended.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from .dictionaries import DOCUMENT_TYPES, PRODUCT_TEXTS, fmt_date
from .money import add_months, dec, money, totals

PRIORITY = ("EXPRESS", "WORKING_CAPITAL", "INVESTMENT")
WORKING_PURPOSES = {"INVENTORY", "CASH_GAP", "CONTRACT_EXECUTION", "GENERAL_NEEDS", "SEASONAL_PURCHASES"}
INVEST_PURPOSES = {"EQUIPMENT", "REAL_ESTATE", "BUSINESS_EXPANSION"}

LINE_HINT = "Если деньги нужны регулярно, банк может предложить кредитную линию по итогам рассмотрения заявки"
INVEST_HINT = "Инвестиционный кредит рассматривает специалист, понадобятся сведения о залоге"
DISCLAIMER = "Ставка и платеж ориентировочные. Точные условия банк рассчитает после проверки заявки, обычно за несколько минут"


def requirements(product: dict[str, Any], applicant_type: str | None) -> list[str]:
    items = []
    if "LEGAL_ENTITY" in product["requires_owner_guarantee_for"]:
        items.append("Для ООО: поручительство собственника" if applicant_type != "LEGAL_ENTITY" else "Поручительство собственника компании")
    if product["requires_collateral"]:
        items.append("Залог: сведения об имуществе и документы")
    for doc in product["required_documents"]:
        items.append(DOCUMENT_TYPES[doc]["title"])
    if not items:
        items.append("Документы не нужны: сведения о бизнесе банк получит сам")
    return items


def match_products(policy: dict[str, Any], purpose: str, amount: Decimal, term_months: int, applicant_type: str | None = None, business_age_months: int | None = None, registration_date: date | None = None) -> dict[str, Any]:
    products = policy["products"]
    cards: list[dict[str, Any]] = []
    for code in PRIORITY:
        p = products[code]
        if not p["direct_application"] or purpose not in p["allowed_purposes"]:
            continue
        if applicant_type and applicant_type not in p["applicant_types"]:
            continue
        if not (dec(p["amount_min"]) <= amount <= dec(p["amount_max"])):
            continue
        term = min(max(term_months, p["term_min_months"]), p["term_max_months"])
        note = None
        if term != term_months:
            note = (
                f"Максимальный срок по этому продукту {p['term_max_months']} мес., платеж рассчитан на него"
                if term_months > p["term_max_months"]
                else f"Минимальный срок по этому продукту {p['term_min_months']} мес., платеж рассчитан на него"
            )
        t = totals(amount, p["base_rate_percent"], term)
        available, reason, eligible = True, None, None
        if business_age_months is not None and business_age_months < p["min_business_age_months"]:
            available = False
            eligible = add_months(registration_date, p["min_business_age_months"]) if registration_date else None
            reason = f"Доступен бизнесу от {p['min_business_age_months']} месяцев работы" + (f", вам будет доступен с {fmt_date(eligible)}" if eligible else "")
        cards.append(
            {
                "product_code": code,
                "name": p["name"],
                "description": PRODUCT_TEXTS[code]["description"],
                "decision_speed": PRODUCT_TEXTS[code]["decision_speed"],
                "review_mode": p["review_mode"],
                "rate_from_percent": str(money(p["base_rate_percent"])),
                "term_months": term,
                "term_note": note,
                "monthly_payment_from": str(t["monthly_payment"]),
                "total_payment_from": str(t["total_payment"]),
                "overpayment_from": str(t["overpayment"]),
                "amount_min": p["amount_min"],
                "amount_max": p["amount_max"],
                "amount_step": p["amount_step"],
                "term_min_months": p["term_min_months"],
                "term_max_months": p["term_max_months"],
                "requirements": requirements(p, applicant_type),
                "required_documents": list(p["required_documents"]),
                "available": available,
                "unavailable_reason": reason,
                "eligible_date": eligible.isoformat() if eligible else None,
                "recommended": False,
                "rank": 0,
            }
        )
    rank = 1
    for card in cards:
        card["rank"] = rank
        rank += 1
    first_available = next((c for c in cards if c["available"]), None)
    if first_available:
        first_available["recommended"] = True
    hints = []
    if purpose in ("SEASONAL_PURCHASES", "CASH_GAP"):
        hints.append(LINE_HINT)
    if any(c["product_code"] == "INVESTMENT" for c in cards) and amount > dec(products["EXPRESS"]["amount_max"]):
        hints.append(INVEST_HINT)
    empty_text = None
    if not cards:
        if amount < dec(products["EXPRESS"]["amount_min"]):
            empty_text = "Минимальная сумма кредита 300 000 руб. Увеличьте сумму или рассмотрите оплату из оборотных средств."
        elif purpose in INVEST_PURPOSES and amount > dec(products["INVESTMENT"]["amount_max"]):
            empty_text = "Онлайн можно оформить до 100 000 000 руб. Уменьшите сумму, и мы покажем варианты."
        elif purpose in WORKING_PURPOSES:
            empty_text = "По этой задаче банк может рассмотреть до 30 000 000 руб. онлайн. Уменьшите сумму, и мы покажем варианты."
        else:
            empty_text = "Подходящих продуктов не нашлось. Измените сумму или срок."
    elif not first_available:
        min_age = min(products[c["product_code"]]["min_business_age_months"] for c in cards)
        eligible = add_months(registration_date, min_age) if registration_date else None
        empty_text = f"Для вашего бизнеса пока нет доступных продуктов: минимальный срок работы {min_age} месяцев." + (f" Вернитесь с {fmt_date(eligible)}." if eligible else "")
    return {"cards": cards, "hints": hints, "empty_text": empty_text, "disclaimer": DISCLAIMER}


def credit_line_view(limit: Decimal, rate_percent: Decimal, tranche_months: int) -> dict[str, str]:
    """Two numbers shown for a credit line (product-catalog.md, section 5.2)."""
    interest = money(dec(limit) * dec(rate_percent) / Decimal(1200))
    return {"monthly_interest_full_use": str(interest), "payment_full_limit_12m": str(totals(limit, rate_percent, tranche_months)["monthly_payment"])}
