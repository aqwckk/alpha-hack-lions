"""Deterministic synthetic borrower profiles (stdlib only).

Specification for services/integrations-mock: for any valid INN that is not
listed in demo_companies.json, the mock builds source responses with
generate_profile(inn, as_of). The same function (with an explicit random
generator) builds the training population in analytics, so the model and the
mock share one data-generating process.

Determinism contract:
- seed = first 16 hex digits of sha256("profile:" + inn) as an integer;
- only random.Random.random() is used (stable across CPython versions),
  every other distribution is derived from it below;
- the result depends only on (inn, as_of); dates are relative to as_of.
"""

from __future__ import annotations

import calendar
import hashlib
import math
import random
from datetime import date, timedelta

from .oracle.inn import complete_ogrn

OKVED = {
    "LOW": [
        ("46.73", "Торговля оптовая лесоматериалами, строительными материалами и санитарно-техническим оборудованием"),
        ("46.90", "Торговля оптовая неспециализированная"),
        ("62.01", "Разработка компьютерного программного обеспечения"),
        ("69.20", "Деятельность по оказанию услуг в области бухгалтерского учета"),
        ("71.12", "Деятельность в области инженерных изысканий и инженерно-технического проектирования"),
        ("86.23", "Стоматологическая практика"),
        ("10.89", "Производство прочих пищевых продуктов, не включенных в другие группировки"),
        ("10.71", "Производство хлеба и мучных кондитерских изделий"),
    ],
    "MEDIUM": [
        ("47.91", "Торговля розничная по почте или по информационно-коммуникационной сети Интернет"),
        ("47.11", "Торговля розничная преимущественно пищевыми продуктами в неспециализированных магазинах"),
        ("49.41", "Деятельность автомобильного грузового транспорта"),
        ("45.20", "Техническое обслуживание и ремонт автотранспортных средств"),
        ("25.62", "Обработка металлических изделий механическая"),
        ("96.02", "Предоставление услуг парикмахерскими и салонами красоты"),
        ("74.20", "Деятельность в области фотографии"),
        ("85.41", "Образование дополнительное детей и взрослых"),
    ],
    "HIGH": [
        ("56.10", "Деятельность ресторанов и услуги по доставке продуктов питания"),
        ("55.10", "Деятельность гостиниц и прочих мест для временного проживания"),
        ("43.22", "Производство санитарно-технических работ, монтаж отопительных систем и систем кондиционирования воздуха"),
        ("41.20", "Строительство жилых и нежилых зданий"),
        ("68.20", "Аренда и управление собственным или арендованным недвижимым имуществом"),
        ("01.13", "Выращивание овощей, бахчевых, корнеплодных и клубнеплодных культур, грибов и трюфелей"),
        ("93.29", "Деятельность зрелищно-развлекательная прочая"),
        ("79.11", "Деятельность туристических агентств"),
    ],
}
OKVED_RISK_GROUPS = {code[:2]: group for group, items in OKVED.items() for code, _ in items}

NAME_ROOTS = ["Пример", "Образец", "Макет", "Эскиз", "Шаблон", "Прототип", "Черновик", "Модель", "Пробник", "Набросок"]
NAME_SUFFIX = {"LOW": ["Трейд", "Софт", "Проект", "Фуд"], "MEDIUM": ["Маркет", "Логистик", "Сервис", "Мастер"], "HIGH": ["Строй", "Вкус", "Тур", "Агро"]}
SURNAMES_M = ["Примеров", "Образцов", "Макетов", "Эскизов", "Шаблонов", "Пробников", "Черновиков", "Набросков"]
FIRST_M = ["Иван", "Петр", "Алексей", "Николай", "Олег", "Павел", "Роман", "Степан"]
FIRST_F = ["Анна", "Мария", "Ольга", "Елена", "Ирина", "Светлана", "Татьяна", "Юлия"]
PATRONYMIC_M = ["Иванович", "Петрович", "Алексеевич", "Николаевич", "Сергеевич", "Павлович"]
PATRONYMIC_F = ["Ивановна", "Петровна", "Алексеевна", "Николаевна", "Сергеевна", "Павловна"]
REGIONS = ["Синтетическая область", "Условный край", "Тестовая республика", "Демонстрационная область"]


class Rng:
    """Distributions built on random.Random.random() only."""

    def __init__(self, seed: int):
        self._r = random.Random(seed)

    def u(self, a: float = 0.0, b: float = 1.0) -> float:
        return a + (b - a) * self._r.random()

    def normal(self, mu: float = 0.0, sd: float = 1.0) -> float:
        # Irwin-Hall approximation: sum of 12 uniforms minus 6 (only + and -,
        # so the result is bit-identical on every IEEE-754 platform).
        z = -6.0
        for _ in range(12):
            z += self._r.random()
        return mu + sd * z

    def bern(self, p: float) -> bool:
        return self._r.random() < p

    def int_between(self, a: int, b: int) -> int:
        return a + min(int(self._r.random() * (b - a + 1)), b - a)

    def choice(self, items, weights=None):
        if weights is None:
            return items[min(int(self._r.random() * len(items)), len(items) - 1)]
        total = sum(weights)
        x = self._r.random() * total
        acc = 0.0
        for item, w in zip(items, weights):
            acc += w
            if x < acc:
                return item
        return items[-1]

    def poisson(self, lam: float) -> int:
        lam = max(lam, 0.0)
        limit = dexp(-lam)
        k, p = 0, self._r.random()
        while p > limit and k < 50:
            k += 1
            p *= self._r.random()
        return k


LN2 = 0.6931471805599453


def dexp(x: float) -> float:
    """exp(x) with only +, -, *, / and exact ldexp: platform-independent result."""
    k = int(round(x / LN2))
    r = x - k * LN2
    term, total = 1.0, 1.0
    for n in range(1, 30):
        term = term * r / n
        total += term
    return math.ldexp(total, k)


def dlog(x: float) -> float:
    """Natural log via frexp (exact) and the atanh series: platform-independent result."""
    if x <= 0:
        raise ValueError("dlog of non-positive value")
    m, e = math.frexp(x)
    z = (m - 1.0) / (m + 1.0)
    z2 = z * z
    term, total = z, 0.0
    for n in range(0, 40):
        total += term / (2 * n + 1)
        term *= z2
    return e * LN2 + 2.0 * total


def dpow(base: float, exponent: float) -> float:
    return dexp(dlog(base) * exponent)


def seed_for(inn: str, salt: str = "profile") -> int:
    return int(hashlib.sha256(f"{salt}:{inn}".encode()).hexdigest()[:16], 16)


def sub_months(d: date, months: int) -> date:
    y = d.year + (d.month - 1 - months) // 12
    m = (d.month - 1 - months) % 12 + 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def _clip(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _rub(x: float) -> str:
    """Whole rubles as a money string (synthetic amounts are whole rubles)."""
    return f"{int(round(x))}.00"


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + dexp(-x))


def generate_borrower(rng: Rng, inn: str, as_of: date, drift: float = 0.0) -> dict:
    """Return {"sources": {...}, "latent": {...}} for one synthetic borrower.

    drift > 0 shifts the population slightly (younger businesses, more credit
    inquiries); used only for the second time cohort of the training data.
    """
    is_ip = len(inn) == 12
    applicant_type = "INDIVIDUAL_ENTREPRENEUR" if is_ip else "LEGAL_ENTITY"
    q = rng.normal()

    # registry
    mu_age = dlog(28 if is_ip else 40) + 0.15 * q - 0.12 * drift
    age = int(_clip(round(dexp(rng.normal(mu_age, 0.9))), 1, 360))
    reg_date = sub_months(as_of, age) - timedelta(days=rng.int_between(0, 20))
    status = rng.choice(
        ["ACTIVE", "LIQUIDATING", "BANKRUPTCY", "REORGANIZING", "CEASED"],
        [985, 6, 3, 2 if not is_ip else 0, 4],
    )
    group = rng.choice(["LOW", "MEDIUM", "HIGH"], [30, 45, 25])
    okved_code, okved_name = rng.choice(OKVED[group])
    region = rng.choice(REGIONS)
    female = rng.bern(0.45)
    surname = rng.choice(SURNAMES_M) + ("а" if female else "")
    first = rng.choice(FIRST_F if female else FIRST_M)
    patronymic = rng.choice(PATRONYMIC_F if female else PATRONYMIC_M)
    person = f"{surname} {first} {patronymic}"
    reg_year = reg_date.year % 100
    if is_ip:
        full_name = f"Индивидуальный предприниматель {person}"
        short_name = f"ИП {surname} {first[0]}.{patronymic[0]}."
        ogrn = complete_ogrn(f"3{reg_year:02d}00{inn[2:4]}{rng.int_between(0, 9999999):07d}")
        founders = []
    else:
        brand = f"{rng.choice(NAME_ROOTS)}-{rng.choice(NAME_SUFFIX[group])}"
        full_name = f"Общество с ограниченной ответственностью \"{brand}\""
        short_name = f"ООО \"{brand}\""
        ogrn = complete_ogrn(f"1{reg_year:02d}00{inn[2:4]}{rng.int_between(0, 99999):05d}")
        founders = [{"name": person, "share_percent": "100.00"}]
        if rng.bern(0.35):
            f2 = f"{rng.choice(SURNAMES_M)} {rng.choice(FIRST_M)} {rng.choice(PATRONYMIC_M)}"
            founders = [{"name": person, "share_percent": "60.00"}, {"name": f2, "share_percent": "40.00"}]

    # revenue and turnover
    mu_rev = dlog(15e6 if is_ip else 70e6) + 0.3 * dlog(max(age, 3) / 36) + 0.15 * q
    annual = _clip(dexp(rng.normal(mu_rev, 0.8)), 1.2e6, 2.0e9)
    monthly = annual / 12
    growth = _clip(rng.normal(0.05 + 0.06 * q, 0.15), -0.6, 1.0)
    sigma = _clip((0.08 + 0.12 * dexp(-0.5 * q)) * rng.u(0.5, 1.5), 0.03, 0.8)
    has_account = rng.bern(0.88 if is_ip else 0.80)
    months_avail = min(12, age)
    if has_account and rng.bern(0.05):
        months_avail = min(months_avail, rng.int_between(3, 11))
    share = rng.u(0.93, 1.0) if rng.bern(0.92) else rng.u(0.65, 0.93)
    inflows: list[str | None] = []
    vals = []
    for t in range(12):
        level = monthly * dpow(1 + growth, (t - 11.5) / 12) * share
        v = level * dexp(rng.normal(0, sigma) - sigma * sigma / 2)
        vals.append(round(v / 100) * 100)
    for t in range(12):
        inflows.append(_rub(vals[t]) if has_account and t >= 12 - months_avail else None)
    if has_account and months_avail > 0:
        avg = sum(vals[12 - months_avail:]) / months_avail
    else:
        avg = 0
    compliance = "RED" if rng.bern(0.004) else "NONE"
    turnover = {
        "has_account": has_account,
        "months_available": months_avail if has_account else 0,
        "inflow_by_month": inflows,
        "avg_monthly_inflow_12m": f"{avg:.2f}" if has_account else "0.00",
        "compliance_flag": compliance,
    }

    # financial statements (LLC only)
    margin = _clip(rng.normal(0.06 + 0.04 * q, 0.07), -0.4, 0.45)
    if is_ip:
        fs = None
    elif age >= 15 and rng.bern(0.92):
        rev_last = annual / dpow(1 + growth, 0.5)
        prev = rev_last / (1 + growth) if age >= 27 else None
        assets = rev_last * rng.u(0.3, 0.9)
        fs = {
            "found": True,
            "report_year": as_of.year - 1,
            "revenue": _rub(rev_last),
            "revenue_prev_year": _rub(prev) if prev is not None else None,
            "net_profit": _rub(rev_last * margin),
            "total_assets": _rub(assets),
            "equity": _rub(assets * _clip(rng.normal(0.35 + 0.1 * q, 0.2), -0.3, 0.9)),
        }
    else:
        fs = {"found": False}

    # FNS
    sme = "MICRO" if annual < 120e6 else ("SMALL" if annual < 800e6 else "MEDIUM")
    if is_ip:
        regime = rng.choice(["USN_INCOME", "USN_INCOME_EXPENSE", "PATENT", "OSN"], [55, 25, 15, 5])
        employees = rng.poisson(1.5 + annual / 15e6)
    else:
        regime = rng.choice(["OSN", "USN_INCOME", "USN_INCOME_EXPENSE"], [40, 25, 35])
        employees = max(1, int(annual / rng.u(3e6, 6e6)))
    arrears = 0.0
    if rng.bern(0.02 * dexp(-0.7 * q)):
        arrears = rng.u(100_000, 2_000_000)
    elif rng.bern(0.04 * dexp(-0.5 * q)):
        arrears = rng.u(1_000, 99_000)
    flags = []
    if rng.bern(0.01):
        flags.append("UNRELIABLE_ADDRESS")
    if not is_ip and rng.bern(0.005):
        flags.append("UNRELIABLE_DIRECTOR")
    if rng.bern(0.025 * dexp(-0.3 * q)):
        flags.append("MASS_ADDRESS")
    if not is_ip and rng.bern(0.01):
        flags.append("MASS_DIRECTOR")
    if not is_ip and rng.bern(0.003):
        flags.append("DISQUALIFIED_DIRECTOR")
    fns = {
        "sme_category": sme,
        "tax_regime": regime,
        "employees_count": employees,
        "tax_arrears_amount": _rub(arrears),
        "taxes_paid_last_year": _rub(annual * rng.u(0.02, 0.06)),
        "unreliable_flags": flags,
    }

    # credit bureau
    no_record = rng.bern(0.25 if age < 12 else (0.10 if is_ip else 0.06))
    if no_record:
        bki = {"no_record": True}
        cur_days = 0
    else:
        hist = age + (rng.int_between(0, 60) if is_ip else 0)
        hist = int(_clip(hist * rng.u(0.3, 1.0), 1, 240))
        loans = min(rng.poisson(0.9 + 0.25 * dlog(max(monthly, 1e5) / 1e6)), 8)
        if loans > 0:
            r = _clip(dexp(rng.normal(dlog(0.07) - 0.15 * q, 0.6)), 0.005, 0.9)
            payments = monthly * r
            debt = payments * rng.u(8, 30)
        else:
            payments = 0.0
            debt = 0.0
        p_clean = _sigmoid(2.2 + 1.0 * q)
        if rng.bern(p_clean):
            max12 = 0
        else:
            bucket = rng.choice([(1, 5), (6, 29), (30, 59), (60, 89), (90, 180)], [40, 30, 15, 8, 7])
            max12 = rng.int_between(*bucket)
        cur_days = 0
        if loans > 0:
            if rng.bern(0.015 * dexp(-0.8 * q)):
                cur_days = rng.int_between(30, 120)
            elif rng.bern(0.02):
                cur_days = rng.int_between(1, 29)
        max12 = max(max12, cur_days)
        max24 = max(max12, rng.int_between(0, 45) if rng.bern(0.15) else 0)
        inq30 = rng.poisson(0.3 + 0.3 * dexp(-0.5 * q) + 0.2 * drift)
        inq90 = inq30 + rng.poisson(0.6 + 0.6 * dexp(-0.5 * q) + 0.3 * drift)
        bki = {
            "no_record": False,
            "active_loans_count": loans,
            "total_debt": _rub(debt),
            "monthly_payments_total": _rub(payments),
            "current_delinquency_days": cur_days,
            "current_delinquency_amount": _rub(payments * rng.u(1, 3)) if cur_days else "0.00",
            "max_delinquency_days_12m": max12,
            "max_delinquency_days_24m": max24,
            "delinquencies_30plus_24m": (1 if max24 >= 30 else 0) + (rng.poisson(0.5) if max24 >= 30 else 0),
            "inquiries_30d": inq30,
            "inquiries_90d": inq90,
            "credit_history_months": hist,
        }

    registry = {
        "found": True,
        "applicant_type": applicant_type,
        "inn": inn,
        "ogrn": ogrn,
        "company_full_name": full_name,
        "company_short_name": short_name,
        "registration_date": reg_date.isoformat(),
        "company_status": status,
        "okved_main_code": okved_code,
        "okved_main_name": okved_name,
        "legal_address_region": region,
        "director_full_name": person,
        "founders": founders,
    }
    return {
        "sources": {
            "REGISTRY": registry,
            "FNS": fns,
            "FINANCIAL_STATEMENTS": fs,
            "CREDIT_BUREAU": bki,
            "BANK_TURNOVER": turnover,
        },
        "latent": {
            "q": q,
            "business_age_months": age,
            "growth": growth,
            "sigma": sigma,
            "share": share,
            "monthly_revenue": monthly,
            "margin": margin,
            "industry_group": group,
            "current_delinquency_days": cur_days,
        },
    }


def not_found_profile(inn: str) -> dict:
    return {
        "REGISTRY": {"found": False, "inn": inn},
        "FNS": None,
        "FINANCIAL_STATEMENTS": None,
        "CREDIT_BUREAU": {"no_record": True},
        "BANK_TURNOVER": {"has_account": False, "months_available": 0, "inflow_by_month": [None] * 12,
                          "avg_monthly_inflow_12m": "0.00", "compliance_flag": "NONE"},
    }


def generate_profile(inn: str, as_of: date) -> dict:
    """Source responses for an INN that is not in demo_companies.json.

    Rule: INN with digits 3-4 equal to "99" (e.g. 0099xxxxxx) is "not found"
    in the registry; this gives the jury a predictable SF_COMPANY_NOT_FOUND.
    """
    if inn[2:4] == "99":
        return not_found_profile(inn)
    return generate_borrower(Rng(seed_for(inn)), inn, as_of)["sources"]


def generate_request(rng: Rng, sources: dict, latent: dict, applicant_type: str) -> dict:
    """Synthetic application parameters (used for the training population and history)."""
    monthly = latent["monthly_revenue"]
    age = latent.get("business_age_months", 36)
    weights = [85, 12, 3] if age < 12 else ([58, 36, 6] if age < 24 else [50, 38, 12])
    product = rng.choice(["EXPRESS", "WORKING_CAPITAL", "INVESTMENT"], weights)
    if product == "EXPRESS":
        amount = _clip(monthly * dexp(rng.normal(dlog(2.0), 0.8)), 300_000, 5_000_000)
        term = rng.choice([6, 12, 18, 24, 36], [10, 30, 20, 30, 10])
        purpose = rng.choice(
            ["INVENTORY", "CASH_GAP", "CONTRACT_EXECUTION", "SEASONAL_PURCHASES", "EQUIPMENT", "REAL_ESTATE", "BUSINESS_EXPANSION", "GENERAL_NEEDS"],
            [25, 20, 8, 10, 15, 4, 6, 12],
        )
    elif product == "WORKING_CAPITAL":
        amount = _clip(monthly * dexp(rng.normal(dlog(1.8), 0.8)), 1_000_000, 30_000_000)
        term = rng.choice([6, 12, 18, 24, 36], [10, 35, 20, 25, 10])
        purpose = rng.choice(["INVENTORY", "CASH_GAP", "CONTRACT_EXECUTION", "SEASONAL_PURCHASES", "GENERAL_NEEDS"], [30, 25, 20, 15, 10])
    else:
        amount = _clip(monthly * dexp(rng.normal(dlog(6.0), 0.6)), 5_000_000, 100_000_000)
        term = rng.choice([36, 48, 60, 84], [20, 25, 35, 20])
        purpose = rng.choice(["EQUIPMENT", "REAL_ESTATE", "BUSINESS_EXPANSION"], [50, 30, 20])
    amount = int(amount // 10_000) * 10_000
    inflate = rng.bern(0.03 * dexp(-0.4 * latent["q"]))
    declared = monthly * (rng.u(1.3, 1.8) if inflate else dexp(rng.normal(0.02, 0.06)))
    bki = sources["CREDIT_BUREAU"] or {}
    bki_pay = float(bki.get("monthly_payments_total") or 0) if not bki.get("no_record", True) else 0.0
    declared_pay = bki_pay * rng.u(0.85, 1.05) if bki_pay > 0 else 0.0
    req = {
        "product_code": product,
        "purpose": purpose,
        "amount": f"{amount}.00",
        "term_months": term,
        "applicant_type": applicant_type,
        "monthly_revenue_declared": _rub(round(declared / 1000) * 1000),
        "existing_monthly_payments_declared": _rub(round(declared_pay / 1000) * 1000),
        "collateral_value": None,
        "collateral_type": None,
    }
    if product == "INVESTMENT":
        req["collateral_value"] = _rub(round(amount * rng.u(0.85, 1.8) / 10_000) * 10_000)
        req["collateral_type"] = rng.choice(["EQUIPMENT", "VEHICLE", "REAL_ESTATE", "PURCHASED_ASSET"])
    return req
