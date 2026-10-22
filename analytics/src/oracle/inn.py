"""INN / OGRN checksums and synthetic identifier generation (stdlib only).

Synthetic identifiers use region code "00", which is never assigned to real
taxpayers, so synthetic data cannot coincide with a real company.
"""

from __future__ import annotations

W10 = (2, 4, 10, 3, 5, 9, 4, 6, 8)
W12_1 = (7, 2, 4, 10, 3, 5, 9, 4, 6, 8)
W12_2 = (3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8)


def _check_digit(digits: str, weights: tuple[int, ...]) -> int:
    return sum(int(d) * w for d, w in zip(digits, weights)) % 11 % 10


def inn_is_valid(inn: str) -> bool:
    if not inn.isdigit():
        return False
    if len(inn) == 10:
        return _check_digit(inn[:9], W10) == int(inn[9])
    if len(inn) == 12:
        return _check_digit(inn[:10], W12_1) == int(inn[10]) and _check_digit(inn[:11], W12_2) == int(inn[11])
    return False


def complete_inn(body: str) -> str:
    """Append check digit(s): 9-digit body gives a 10-digit INN, 10-digit body gives 12 digits."""
    if len(body) == 9:
        return body + str(_check_digit(body, W10))
    if len(body) == 10:
        c1 = _check_digit(body, W12_1)
        c2 = _check_digit(body + str(c1), W12_2)
        return body + str(c1) + str(c2)
    raise ValueError("body must have 9 or 10 digits")


def ogrn_is_valid(ogrn: str) -> bool:
    if not ogrn.isdigit():
        return False
    if len(ogrn) == 13:
        return int(ogrn[:12]) % 11 % 10 == int(ogrn[12])
    if len(ogrn) == 15:
        return int(ogrn[:14]) % 13 % 10 == int(ogrn[14])
    return False


def complete_ogrn(body: str) -> str:
    """12-digit body gives OGRN (13 digits), 14-digit body gives OGRNIP (15 digits)."""
    if len(body) == 12:
        return body + str(int(body) % 11 % 10)
    if len(body) == 14:
        return body + str(int(body) % 13 % 10)
    raise ValueError("body must have 12 or 14 digits")


def mask_inn(inn: str) -> str:
    """Masking for logs: 1234******56 style (first 4 and last 2 digits)."""
    if len(inn) < 6:
        return "*" * len(inn)
    return inn[:4] + "*" * (len(inn) - 6) + inn[-2:]
