"""Rendering of the standard loan documents for the EDO simulator (plain UTF-8 text)."""

from __future__ import annotations

import hashlib
from decimal import Decimal
from typing import Any

TITLES = {
    "CREDIT_AGREEMENT": "Кредитный договор",
    "CREDIT_LINE_AGREEMENT": "Договор кредитной линии",
    "PAYMENT_SCHEDULE": "График платежей",
    "GUARANTEE_AGREEMENT": "Договор поручительства",
    "PLEDGE_AGREEMENT": "Договор залога",
}

HEADER = "СИНТЕТИЧЕСКИЙ ДОКУМЕНТ ПРОТОТИПА. НЕ ЯВЛЯЕТСЯ ОФЕРТОЙ И НЕ ИМЕЕТ ЮРИДИЧЕСКОЙ СИЛЫ."


def _money(value: Any) -> str:
    if value is None:
        return "-"
    whole, _, frac = f"{Decimal(str(value)):.2f}".partition(".")
    groups = []
    sign = "-" if whole.startswith("-") else ""
    whole = whole.lstrip("-")
    while whole:
        groups.insert(0, whole[-3:])
        whole = whole[:-3]
    return f"{sign}{' '.join(groups)},{frac} руб."


def _agreement(doc_type: str, number: str, req: dict[str, Any]) -> str:
    terms = req["terms"]
    applicant = req["applicant"]
    is_line = terms.get("product_code") == "CREDIT_LINE"
    lines = [
        HEADER,
        "",
        f"{TITLES['CREDIT_LINE_AGREEMENT' if is_line else 'CREDIT_AGREEMENT']} N {number}",
        f"Заявка: {req.get('application_number', '-')}",
        f"Заемщик: {applicant.get('name', '-')} (ИНН {applicant.get('inn', '-')})",
        f"Продукт: {terms.get('product_name', terms.get('product_code'))}",
    ]
    if is_line:
        lines += [
            f"Лимит кредитной линии: {_money(terms['amount'])}",
            f"Срок действия линии: {terms['term_months']} мес.",
            f"Максимальный срок транша: {terms.get('tranche_max_term_months') or 12} мес.",
        ]
    else:
        lines += [
            f"Сумма кредита: {_money(terms['amount'])}",
            f"Срок: {terms['term_months']} мес.",
        ]
    lines += [
        f"Процентная ставка: {terms['rate_percent']}% годовых",
        f"Ежемесячный платеж: {_money(terms['monthly_payment'])}",
        f"Итого выплат: {_money(terms.get('total_payment'))}",
        f"Переплата: {_money(terms.get('overpayment'))}",
        "",
        "1. Банк предоставляет заемщику денежные средства на условиях настоящего договора.",
        "2. Заемщик возвращает кредит и уплачивает проценты ежемесячными аннуитетными платежами.",
        "3. Договор подписывается простой электронной подписью в кабинете клиента.",
    ]
    return "\n".join(lines) + "\n"


def _schedule(number: str, req: dict[str, Any]) -> str:
    rows = req.get("schedule") or []
    lines = [HEADER, "", f"График платежей к договору N {number}", "", "N | Дата | Платеж | Проценты | Основной долг | Остаток"]
    for row in rows:
        lines.append(
            f"{row['n']} | {row['date']} | {row['payment']} | {row['interest']} | {row['principal']} | {row['balance']}"
        )
    return "\n".join(lines) + "\n"


def _guarantee(number: str, req: dict[str, Any]) -> str:
    applicant = req["applicant"]
    return "\n".join(
        [
            HEADER,
            "",
            f"Договор поручительства к договору N {number}",
            f"Поручитель: {applicant.get('guarantor_name') or 'собственник компании'}",
            f"Должник: {applicant.get('name', '-')} (ИНН {applicant.get('inn', '-')})",
            f"Обеспечиваемое обязательство: {_money(req['terms']['amount'])}",
            "Поручитель отвечает перед банком солидарно с должником.",
        ]
    ) + "\n"


def _pledge(number: str, req: dict[str, Any]) -> str:
    collateral = req.get("collateral") or {}
    return "\n".join(
        [
            HEADER,
            "",
            f"Договор залога к договору N {number}",
            f"Залогодатель: {req['applicant'].get('name', '-')}",
            f"Предмет залога: {collateral.get('type', '-')}, {collateral.get('description', '-')}",
            f"Залоговая стоимость (заявленная): {_money(collateral.get('value'))}",
        ]
    ) + "\n"


def render_package(number: str, req: dict[str, Any]) -> list[dict[str, Any]]:
    docs = []
    for doc_type in req["documents"]:
        if doc_type == "CREDIT_AGREEMENT":
            content = _agreement(doc_type, number, req)
            title = TITLES["CREDIT_LINE_AGREEMENT" if req["terms"].get("product_code") == "CREDIT_LINE" else "CREDIT_AGREEMENT"]
        elif doc_type == "PAYMENT_SCHEDULE":
            content, title = _schedule(number, req), TITLES[doc_type]
        elif doc_type == "GUARANTEE_AGREEMENT":
            content, title = _guarantee(number, req), TITLES[doc_type]
        elif doc_type == "PLEDGE_AGREEMENT":
            content, title = _pledge(number, req), TITLES[doc_type]
        else:
            raise ValueError(doc_type)
        docs.append(
            {
                "document_type": doc_type,
                "title": title,
                "content_type": "text/plain; charset=utf-8",
                "content": content,
                "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
            }
        )
    return docs
