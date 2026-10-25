"""Money arithmetic: Decimal only (prec 28), ROUND_HALF_UP to kopecks, ratios to 4 decimals.

Rules follow analytics/artifacts/README.md, section 1, and product-catalog.md, section 5.
"""

from __future__ import annotations

import calendar
from datetime import date
from decimal import ROUND_DOWN, ROUND_HALF_UP, Context, Decimal, localcontext

KOPECK = Decimal("0.01")
RATIO_Q = Decimal("0.0001")
CTX = Context(prec=28)
ZERO = Decimal("0.00")


def dec(value) -> Decimal:
    """str/int/Decimal to Decimal; float is a programming error for money."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        raise TypeError("float is not allowed for money")
    return Decimal(str(value))


def money(value) -> Decimal:
    return dec(value).quantize(KOPECK, rounding=ROUND_HALF_UP)


def ratio(numerator, denominator) -> Decimal:
    with localcontext(CTX):
        return (dec(numerator) / dec(denominator)).quantize(RATIO_Q, rounding=ROUND_HALF_UP)


def monthly_rate(rate_percent) -> Decimal:
    with localcontext(CTX):
        return dec(rate_percent) / Decimal(1200)


def annuity_factor(rate_percent, term_months: int) -> Decimal:
    """(1 - (1 + i)^-n) / i without rounding."""
    with localcontext(CTX):
        i = monthly_rate(rate_percent)
        if i == 0:
            return Decimal(term_months)
        return (Decimal(1) - (Decimal(1) + i) ** (-term_months)) / i


def annuity_payment(amount, rate_percent, term_months: int) -> Decimal:
    """P = S * i / (1 - (1 + i)^-n), HALF_UP to kopecks."""
    with localcontext(CTX):
        s = dec(amount)
        i = monthly_rate(rate_percent)
        if i == 0:
            return money(s / term_months)
        return money(s * i / (Decimal(1) - (Decimal(1) + i) ** (-term_months)))


def floor_to_step(value, step) -> Decimal:
    with localcontext(CTX):
        v, st = dec(value), dec(step)
        if v <= 0:
            return ZERO
        return money((v / st).to_integral_value(rounding=ROUND_DOWN) * st)


def max_amount_for_payment(allowed_payment, rate_percent, term_months: int, amount_max, rounding_step) -> Decimal:
    """S_max = allowed * (1 - (1+i)^-n) / i, capped by amount_max and floored to the rounding step."""
    with localcontext(CTX):
        raw = dec(allowed_payment) * annuity_factor(rate_percent, term_months)
        return floor_to_step(min(raw, dec(amount_max)), rounding_step)


def totals(amount, rate_percent, term_months: int) -> dict[str, Decimal]:
    payment = annuity_payment(amount, rate_percent, term_months)
    total = money(amount) if dec(rate_percent) == 0 else money(payment * term_months)
    return {"monthly_payment": payment, "total_payment": total, "overpayment": money(total - dec(amount))}


def add_months(d: date, months: int) -> date:
    y = d.year + (d.month - 1 + months) // 12
    m = (d.month - 1 + months) % 12 + 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def months_between(start: date, end: date) -> int:
    """Full calendar months from start to end (0 if end is earlier)."""
    m = (end.year - start.year) * 12 + (end.month - start.month)
    if end.day < start.day:
        m -= 1
    return max(m, 0)


def payment_schedule(amount, rate_percent, term_months: int, first_payment: date) -> list[dict[str, str]]:
    """Annuity schedule: interest = balance * i (A-31), the last payment closes the balance to exactly 0.00."""
    with localcontext(CTX):
        balance = money(amount)
        i = monthly_rate(rate_percent)
        payment = annuity_payment(amount, rate_percent, term_months)
        rows = []
        for n in range(1, term_months + 1):
            interest = money(balance * i)
            if n == term_months:
                principal = balance
                pay = money(principal + interest)
            else:
                principal = money(payment - interest)
                pay = payment
            balance = money(balance - principal)
            rows.append(
                {
                    "n": n,
                    "date": add_months(first_payment, n - 1).isoformat(),
                    "payment": str(pay),
                    "interest": str(interest),
                    "principal": str(principal),
                    "balance": str(balance),
                }
            )
        return rows
