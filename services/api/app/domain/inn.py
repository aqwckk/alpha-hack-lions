"""INN checksum (data-requirements.md, section 2) and masking for logs."""

from __future__ import annotations

W10 = (2, 4, 10, 3, 5, 9, 4, 6, 8)
W12_1 = (7, 2, 4, 10, 3, 5, 9, 4, 6, 8)
W12_2 = (3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8)


def _check(digits: str, weights: tuple[int, ...]) -> int:
    return sum(int(d) * w for d, w in zip(digits, weights, strict=False)) % 11 % 10


def inn_error(inn: str) -> str | None:
    """None if valid, otherwise INN_LENGTH or INN_CHECKSUM."""
    if not inn.isdigit() or len(inn) not in (10, 12):
        return "INN_LENGTH"
    if len(inn) == 10:
        ok = _check(inn[:9], W10) == int(inn[9])
    else:
        ok = _check(inn[:10], W12_1) == int(inn[10]) and _check(inn[:11], W12_2) == int(inn[11])
    return None if ok else "INN_CHECKSUM"


def applicant_type_for(inn: str) -> str:
    return "LEGAL_ENTITY" if len(inn) == 10 else "INDIVIDUAL_ENTREPRENEUR"


def mask_inn(inn: str | None) -> str | None:
    if not inn:
        return inn
    if len(inn) < 6:
        return "*" * len(inn)
    return inn[:4] + "*" * (len(inn) - 6) + inn[-2:]
