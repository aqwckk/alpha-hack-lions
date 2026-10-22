"""Field rules of the client form (data-requirements.md, section 1): format on autosave, completeness on submit."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any

from ..enums import CollateralOwner, CollateralType, Purpose, RepresentativeRole
from .dictionaries import VALIDATION_MESSAGES, fmt_money, render
from .inn import applicant_type_for, inn_error

MAX_MONEY = Decimal("10000000000")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

MONEY_FIELDS = ("amount", "monthly_revenue_declared", "existing_monthly_payments_declared", "collateral_value", "own_contribution_amount")
TEXT_LIMITS = {"collateral_description": (10, 500), "investment_project_description": (20, 2000), "client_comment": (0, 1000)}
ENUMS = {
    "purpose": Purpose,
    "representative_role": RepresentativeRole,
    "collateral_type": CollateralType,
    "collateral_owner": CollateralOwner,
}
EDITABLE_FIELDS = (
    "purpose", "amount", "term_months", "applicant_inn", "representative_role", "monthly_revenue_declared",
    "existing_monthly_payments_declared", "owner_guarantee_agreed", "collateral_type", "collateral_description",
    "collateral_value", "collateral_owner", "investment_project_description", "own_contribution_amount", "client_comment",
)


def field_error(field: str, code: str, **values: Any) -> dict[str, Any]:
    return {"field": field, "code": code, "message": render(VALIDATION_MESSAGES[code], values)}


def clean_text(value: str) -> str:
    return _CONTROL.sub("", value).strip()


def normalize(field: str, value: Any) -> tuple[Any, dict[str, Any] | None]:
    """Format/type check of one field. Returns (normalized value, error or None). None clears a field."""
    if value is None:
        return None, None
    if field in MONEY_FIELDS:
        try:
            d = Decimal(str(value))
        except (InvalidOperation, ValueError):
            return None, field_error(field, "INVALID_FORMAT", hint="сумма в рублях, например 1500000")
        if not d.is_finite() or d < 0 or d > MAX_MONEY or d != d.quantize(Decimal("0.01")):
            return None, field_error(field, "INVALID_FORMAT", hint="сумма в рублях, не больше 10 000 000 000")
        if field == "amount" and d != d.to_integral_value():
            return None, field_error(field, "INVALID_FORMAT", hint="сумма кредита в целых рублях")
        return d.quantize(Decimal("0.01")), None
    if field == "term_months":
        if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 120:
            return None, field_error(field, "INVALID_FORMAT", hint="число месяцев")
        return value, None
    if field == "applicant_inn":
        inn = re.sub(r"\s+", "", str(value))
        if not inn.isdigit() or len(inn) not in (10, 12):
            return None, field_error(field, "INN_LENGTH")
        if inn_error(inn):
            return None, field_error(field, "INN_CHECKSUM")
        return inn, None
    if field == "owner_guarantee_agreed":
        if not isinstance(value, bool):
            return None, field_error(field, "INVALID_FORMAT", hint="да или нет")
        return value, None
    if field in ENUMS:
        if value not in ENUMS[field].__members__:
            return None, field_error(field, "INVALID_FORMAT", hint="значение из списка")
        return value, None
    if field in TEXT_LIMITS:
        if not isinstance(value, str):
            return None, field_error(field, "INVALID_FORMAT", hint="текст")
        text = clean_text(value)
        if len(text) > TEXT_LIMITS[field][1]:
            return None, field_error(field, "INVALID_FORMAT", hint=f"не больше {TEXT_LIMITS[field][1]} символов")
        return text or None, None
    raise KeyError(field)


def submit_errors(app: dict[str, Any], product: dict[str, Any]) -> list[dict[str, Any]]:
    """Full check before SUBMIT: required fields by product, ranges, step, purpose, guarantee."""
    errors: list[dict[str, Any]] = []
    required = ["purpose", "amount", "term_months", "applicant_inn", "representative_role", "monthly_revenue_declared", "existing_monthly_payments_declared"]
    if product["requires_collateral"]:
        required += ["collateral_type", "collateral_description", "collateral_value", "collateral_owner", "investment_project_description"]
    for f in required:
        if app.get(f) in (None, ""):
            errors.append(field_error(f, "REQUIRED"))
    if app.get("purpose") and app["purpose"] not in product["allowed_purposes"]:
        errors.append(field_error("purpose", "PURPOSE_NOT_ALLOWED"))
    amount = app.get("amount")
    if amount is not None:
        lo, hi = Decimal(product["amount_min"]), Decimal(product["amount_max"])
        if not lo <= amount <= hi:
            errors.append(field_error("amount", "OUT_OF_RANGE", min=fmt_money(lo), max=fmt_money(hi)))
        elif amount % Decimal(product["amount_step"]) != 0:
            errors.append(field_error("amount", "NOT_MULTIPLE_OF_STEP", step=fmt_money(product["amount_step"]).replace(" руб.", "")))
    term = app.get("term_months")
    if term is not None and not product["term_min_months"] <= term <= product["term_max_months"]:
        errors.append(field_error("term_months", "OUT_OF_RANGE", min=f"{product['term_min_months']} мес.", max=f"{product['term_max_months']} мес."))
    revenue = app.get("monthly_revenue_declared")
    if revenue is not None and revenue <= 0:
        errors.append(field_error("monthly_revenue_declared", "INVALID_FORMAT", hint="выручка больше 0"))
    inn = app.get("applicant_inn")
    if inn:
        code = inn_error(inn)
        if code:
            errors.append(field_error("applicant_inn", code))
        else:
            atype = applicant_type_for(inn)
            if atype not in product["applicant_types"]:
                errors.append(field_error("applicant_inn", "APPLICANT_TYPE_NOT_ALLOWED"))
            if atype in product["requires_owner_guarantee_for"] and app.get("owner_guarantee_agreed") is not True:
                errors.append(field_error("owner_guarantee_agreed", "GUARANTEE_REQUIRED"))
    for f, (lo, _hi) in TEXT_LIMITS.items():
        v = app.get(f)
        if v and len(v) < lo:
            errors.append(field_error(f, "INVALID_FORMAT", hint=f"не меньше {lo} символов"))
    if product["requires_collateral"] and app.get("collateral_value") is not None and app["collateral_value"] <= 0:
        errors.append(field_error("collateral_value", "INVALID_FORMAT", hint="стоимость больше 0"))
    return errors


def warnings_for(app: dict[str, Any]) -> list[dict[str, Any]]:
    revenue, payments = app.get("monthly_revenue_declared"), app.get("existing_monthly_payments_declared")
    if revenue is not None and payments is not None and payments > revenue:
        return [field_error("existing_monthly_payments_declared", "PAYMENTS_ABOVE_REVENUE")]
    return []
