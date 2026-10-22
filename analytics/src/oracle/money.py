"""Money and rate arithmetic shared by scoring and policy.

Rules (identical in the backend):
- all money and ratio arithmetic uses decimal.Decimal in a context with
  prec=28 (Python default), never float;
- money results are rounded ROUND_HALF_UP to kopecks (0.01);
- ratios used as scorecard features or policy inputs are rounded
  ROUND_HALF_UP to 4 decimal places;
- annual rates are percent per annum with 2 decimals, e.g. Decimal("23.50").
"""

from __future__ import annotations

from decimal import ROUND_DOWN, ROUND_HALF_UP, Context, Decimal, localcontext

KOPECK = Decimal("0.01")
RATIO_Q = Decimal("0.0001")
CTX = Context(prec=28)


def D(value) -> Decimal:
    """Convert int/str/Decimal to Decimal. Floats are rejected on purpose."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        raise TypeError("float is not allowed for money, pass str or int")
    return Decimal(str(value))


def money(value) -> Decimal:
    return D(value).quantize(KOPECK, rounding=ROUND_HALF_UP)


def ratio(numerator, denominator) -> Decimal:
    with localcontext(CTX):
        return (D(numerator) / D(denominator)).quantize(RATIO_Q, rounding=ROUND_HALF_UP)


def monthly_rate(rate_percent) -> Decimal:
    with localcontext(CTX):
        return D(rate_percent) / Decimal(1200)


def annuity_payment(amount, rate_percent, term_months: int) -> Decimal:
    """P = S * i / (1 - (1 + i)^(-n)), rounded HALF_UP to kopecks."""
    with localcontext(CTX):
        s = D(amount)
        i = monthly_rate(rate_percent)
        if i == 0:
            return money(s / term_months)
        p = s * i / (Decimal(1) - (Decimal(1) + i) ** (-term_months))
        return money(p)


def annuity_factor(rate_percent, term_months: int) -> Decimal:
    """(1 - (1 + i)^(-n)) / i, unrounded (context precision)."""
    with localcontext(CTX):
        i = monthly_rate(rate_percent)
        if i == 0:
            return Decimal(term_months)
        return (Decimal(1) - (Decimal(1) + i) ** (-term_months)) / i


def floor_to_step(value, step) -> Decimal:
    with localcontext(CTX):
        v = D(value)
        st = D(step)
        if v <= 0:
            return Decimal("0.00")
        return money((v / st).to_integral_value(rounding=ROUND_DOWN) * st)


def max_amount_for_payment(allowed_payment, rate_percent, term_months: int, amount_max, rounding_step) -> Decimal:
    """S_max = allowed * (1 - (1+i)^-n) / i, capped by amount_max, floored to rounding_step."""
    with localcontext(CTX):
        raw = D(allowed_payment) * annuity_factor(rate_percent, term_months)
        capped = min(raw, D(amount_max))
        return floor_to_step(capped, rounding_step)


def schedule_totals(amount, rate_percent, term_months: int) -> dict:
    p = annuity_payment(amount, rate_percent, term_months)
    total = money(p * term_months)
    return {
        "monthly_payment": p,
        "total_payment": total,
        "overpayment": money(total - D(amount)),
    }
