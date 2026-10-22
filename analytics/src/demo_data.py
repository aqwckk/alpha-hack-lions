"""Demo companies (scenarios S1-S5 and extra profiles for the jury) and demo users."""

from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from .mockgen import sub_months
from .oracle.inn import complete_inn, complete_ogrn, inn_is_valid, ogrn_is_valid

REFERENCE_DATE = date(2026, 10, 23)

STABLE = [0.95, 1.03, 0.98, 1.02, 0.96, 1.04, 0.97, 1.05, 0.99, 1.01, 0.96, 1.04]
NORMAL = [0.88, 1.10, 0.95, 1.08, 0.90, 1.12, 0.93, 1.07, 0.97, 1.05, 0.89, 1.06]
VOLATILE = [0.55, 1.45, 0.70, 1.30, 0.60, 1.50, 0.80, 1.20, 0.65, 1.40, 0.75, 1.10]


def inflows(avg: int, pattern: list[float], growth: float = 0.0, months: int = 12) -> list[str | None]:
    out: list[str | None] = []
    for t, k in enumerate(pattern):
        v = avg * k * (1 + growth) ** ((t - 5.5) / 12)
        out.append(f"{int(round(v / 1000) * 1000)}.00")
    return [None] * (12 - months) + out[12 - months:]


def avg_of(values: list[str | None]) -> str:
    vals = [Decimal(v) for v in values if v is not None]
    if not vals:
        return "0.00"
    return str((sum(vals) / len(vals)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def turnover(values: list[str | None] | None, compliance: str = "NONE") -> dict:
    if values is None:
        return {"has_account": False, "months_available": 0, "inflow_by_month": [None] * 12,
                "avg_monthly_inflow_12m": "0.00", "compliance_flag": compliance}
    return {"has_account": True, "months_available": sum(1 for v in values if v is not None),
            "inflow_by_month": values, "avg_monthly_inflow_12m": avg_of(values), "compliance_flag": compliance}


def bki(history: int, loans: int, payments: int, inq90: int, inq30: int = 0, max12: int = 0, max24: int | None = None,
        current_days: int = 0, current_amount: int = 0) -> dict:
    return {
        "no_record": False,
        "active_loans_count": loans,
        "total_debt": f"{payments * 18}.00",
        "monthly_payments_total": f"{payments}.00",
        "current_delinquency_days": current_days,
        "current_delinquency_amount": f"{current_amount}.00",
        "max_delinquency_days_12m": max12,
        "max_delinquency_days_24m": max(max12, max24 or 0),
        "delinquencies_30plus_24m": 1 if max(max12, max24 or 0) >= 30 else 0,
        "inquiries_30d": inq30,
        "inquiries_90d": inq90,
        "credit_history_months": history,
    }


def fns(regime: str, employees: int, arrears: int = 0, flags=None, sme: str = "MICRO", taxes: int = 0) -> dict:
    return {"sme_category": sme, "tax_regime": regime, "employees_count": employees,
            "tax_arrears_amount": f"{arrears}.00", "taxes_paid_last_year": f"{taxes}.00", "unreliable_flags": flags or []}


def fs(revenue: int, prev: int | None, profit: int, year: int = 2025) -> dict:
    return {"found": True, "report_year": year, "revenue": f"{revenue}.00",
            "revenue_prev_year": f"{prev}.00" if prev is not None else None, "net_profit": f"{profit}.00",
            "total_assets": f"{int(revenue * 0.6)}.00", "equity": f"{int(revenue * 0.25)}.00"}


def registry(inn, ogrn_body, full, short, months_ago, status, okved, okved_name, region, director, founders):
    is_ip = len(inn) == 12
    return {
        "found": True,
        "applicant_type": "INDIVIDUAL_ENTREPRENEUR" if is_ip else "LEGAL_ENTITY",
        "inn": inn,
        "ogrn": complete_ogrn(ogrn_body),
        "company_full_name": full,
        "company_short_name": short,
        "registration_date": sub_months(REFERENCE_DATE, months_ago).isoformat(),
        "company_status": status,
        "okved_main_code": okved,
        "okved_main_name": okved_name,
        "legal_address_region": region,
        "director_full_name": director,
        "founders": founders,
    }


def app(product, purpose, amount, term, revenue, payments, applicant_type, collateral_value=None, collateral_type=None):
    return {"product_code": product, "purpose": purpose, "amount": f"{amount}.00", "term_months": term,
            "applicant_type": applicant_type, "monthly_revenue_declared": f"{revenue}.00",
            "existing_monthly_payments_declared": f"{payments}.00",
            "collateral_value": f"{collateral_value}.00" if collateral_value else None, "collateral_type": collateral_type}


LE, IE = "LEGAL_ENTITY", "INDIVIDUAL_ENTREPRENEUR"


def companies() -> list[dict]:
    inn = {
        "S1": complete_inn("0020000101"), "S2": complete_inn("001000201"), "S3": complete_inn("001000301"),
        "S4": complete_inn("0020000401"), "S5": complete_inn("001000501"),
        "X1": complete_inn("001000601"), "X2": complete_inn("0020000701"), "X3": complete_inn("001000801"),
        "X4": complete_inn("0020000901"), "X5": complete_inn("0020001001"), "X6": complete_inn("001001101"),
        "X7": complete_inn("001001201"),
    }
    out = []

    def add(pid, scenario, title, login, months_ago, sources, requests, behavior=None, note=""):
        out.append({"profile_id": pid, "scenario": scenario, "title": title, "inn": inn[pid],
                    "applicant_type": sources["REGISTRY"]["applicant_type"], "client_login": login,
                    "registration_months_ago": months_ago, "note": note,
                    "mock_behavior": behavior or {}, "sources": sources, "demo_requests": requests})

    # S1: IP, cafe, 36 months, clean, approved
    i = inn["S1"]
    add("S1", "S1", "ИП, кофейня: автоодобрение экспресс-кредита", "client.irina", 36, {
        "REGISTRY": registry(i, "32300200000101", "Индивидуальный предприниматель Примерова Ирина Олеговна", "ИП Примерова И.О.", 36,
                             "ACTIVE", "56.10", "Деятельность ресторанов и услуги по доставке продуктов питания", "Синтетическая область",
                             "Примерова Ирина Олеговна", []),
        "FNS": fns("USN_INCOME", 6, taxes=540000),
        "FINANCIAL_STATEMENTS": None,
        "CREDIT_BUREAU": bki(history=64, loans=0, payments=0, inq90=0),
        "BANK_TURNOVER": turnover(inflows(1520000, STABLE, 0.10)),
    }, [{"request_id": "S1", "application": app("EXPRESS", "EQUIPMENT", 1200000, 24, 1500000, 0, IE)}])

    # S2: LLC, ventilation works, 72 months, counter-offer
    i = inn["S2"]
    add("S2", "S2", "ООО, монтаж вентиляции: контрпредложение по оборотному кредиту", "client.andrey", 72, {
        "REGISTRY": registry(i, "120001000201", "Общество с ограниченной ответственностью \"Эскиз-Климат\"", "ООО \"Эскиз-Климат\"", 72,
                             "ACTIVE", "43.22", "Производство санитарно-технических работ, монтаж отопительных систем и систем кондиционирования воздуха",
                             "Условный край", "Образцов Андрей Николаевич",
                             [{"name": "Образцов Андрей Николаевич", "share_percent": "70.00"}, {"name": "Макетов Павел Сергеевич", "share_percent": "30.00"}]),
        "FNS": fns("OSN", 38, sme="MICRO", taxes=3900000),
        "FINANCIAL_STATEMENTS": fs(88000000, 82000000, 6200000),
        "CREDIT_BUREAU": bki(history=66, loans=2, payments=950000, inq90=1),
        "BANK_TURNOVER": turnover(inflows(7450000, STABLE, 0.08)),
    }, [{"request_id": "S2", "application": app("WORKING_CAPITAL", "CASH_GAP", 15000000, 12, 7500000, 950000, LE)}])

    # S3: LLC, food production, 108 months, no account in the bank, mismatch 35%
    i = inn["S3"]
    x_rev = 60000000
    add("S3", "S3", "ООО, пищевое производство: инвестиционный кредит, расхождение выручки и ручное рассмотрение", "client.marina", 108, {
        "REGISTRY": registry(i, "117001000301", "Общество с ограниченной ответственностью \"Образец-Фуд\"", "ООО \"Образец-Фуд\"", 108,
                             "ACTIVE", "10.89", "Производство прочих пищевых продуктов, не включенных в другие группировки",
                             "Тестовая республика", "Шаблонова Марина Петровна",
                             [{"name": "Шаблонова Марина Петровна", "share_percent": "55.00"}, {"name": "Черновиков Роман Иванович", "share_percent": "45.00"}]),
        "FNS": fns("OSN", 64, sme="MICRO", taxes=2700000),
        "FINANCIAL_STATEMENTS": fs(x_rev, 53500000, 4900000),
        "CREDIT_BUREAU": bki(history=96, loans=2, payments=600000, inq90=1),
        "BANK_TURNOVER": turnover(None),
    }, [
        {"request_id": "S3", "application": app("INVESTMENT", "EQUIPMENT", 40000000, 60, x_rev * 135 // 100 // 12, 600000, LE, 48000000, "PURCHASED_ASSET")},
        {"request_id": "S3-AFTER-INFO", "state": {"manual_review_required": True},
         "application": app("INVESTMENT", "EQUIPMENT", 40000000, 60, x_rev * 135 // 100 // 12, 600000, LE, 48000000, "PURCHASED_ASSET"),
         "note": "повторный проход после ответа на дозапрос андеррайтера (шаг 9 сценария S3)"},
    ])

    # S4: IP, online store, 4 months, current delinquency
    i = inn["S4"]
    add("S4", "S4", "Начинающий ИП, интернет-магазин: отказ по двум стоп-факторам", "client.sergey", 4, {
        "REGISTRY": registry(i, "32600200000401", "Индивидуальный предприниматель Пробников Сергей Алексеевич", "ИП Пробников С.А.", 4,
                             "ACTIVE", "47.91", "Торговля розничная по почте или по информационно-коммуникационной сети Интернет",
                             "Демонстрационная область", "Пробников Сергей Алексеевич", []),
        "FNS": fns("USN_INCOME", 1, taxes=0),
        "FINANCIAL_STATEMENTS": None,
        "CREDIT_BUREAU": bki(history=26, loans=1, payments=38000, inq90=5, inq30=3, max12=45, current_days=45, current_amount=76000),
        "BANK_TURNOVER": turnover(inflows(420000, VOLATILE, 0.0, months=4)),
    }, [{"request_id": "S4", "application": app("EXPRESS", "INVENTORY", 2000000, 12, 600000, 0, IE)}])

    # S5: LLC, wholesale, 50 months, credit bureau timeouts on first 4 requests
    i = inn["S5"]
    add("S5", "S5", "ООО, оптовая торговля: сбой БКИ с повтором, затем одобрение", "client.oleg", 50, {
        "REGISTRY": registry(i, "122001000501", "Общество с ограниченной ответственностью \"Макет-Трейд\"", "ООО \"Макет-Трейд\"", 50,
                             "ACTIVE", "46.73", "Торговля оптовая лесоматериалами, строительными материалами и санитарно-техническим оборудованием",
                             "Синтетическая область", "Набросков Олег Павлович", [{"name": "Набросков Олег Павлович", "share_percent": "100.00"}]),
        "FNS": fns("USN_INCOME_EXPENSE", 22, taxes=1600000),
        "FINANCIAL_STATEMENTS": fs(70000000, 66000000, 4300000),
        "CREDIT_BUREAU": bki(history=48, loans=1, payments=300000, inq90=1),
        "BANK_TURNOVER": turnover(inflows(6000000, STABLE, 0.06)),
    }, [{"request_id": "S5", "application": app("EXPRESS", "INVENTORY", 3000000, 24, 6000000, 300000, LE)}],
        behavior={"CREDIT_BUREAU": {"fail_first_n": 4, "failure": "TIMEOUT"}},
        note="Мок БКИ отвечает таймаутом на первые 4 запроса по этому ИНН (счетчик сбрасывается через служебный endpoint мока)")

    # X1: liquidating LLC
    i = inn["X1"]
    add("X1", "EXTRA", "ООО в стадии ликвидации: отказ SF_COMPANY_STATUS", "client.demo", 60, {
        "REGISTRY": registry(i, "121001000601", "Общество с ограниченной ответственностью \"Набросок-Строй\"", "ООО \"Набросок-Строй\"", 60,
                             "LIQUIDATING", "41.20", "Строительство жилых и нежилых зданий", "Условный край", "Эскизов Николай Петрович",
                             [{"name": "Эскизов Николай Петрович", "share_percent": "100.00"}]),
        "FNS": fns("OSN", 12, taxes=800000),
        "FINANCIAL_STATEMENTS": fs(30000000, 34000000, -900000),
        "CREDIT_BUREAU": bki(history=40, loans=1, payments=120000, inq90=2),
        "BANK_TURNOVER": turnover(inflows(2300000, NORMAL, -0.10)),
    }, [{"request_id": "X1", "application": app("EXPRESS", "GENERAL_NEEDS", 1000000, 12, 2400000, 120000, LE)}])

    # X2: IP with tax arrears above the stop amount
    i = inn["X2"]
    add("X2", "EXTRA", "ИП с налоговой недоимкой: отказ SF_TAX_ARREARS", "client.demo", 40, {
        "REGISTRY": registry(i, "32300200000701", "Индивидуальный предприниматель Шаблонова Татьяна Ивановна", "ИП Шаблонова Т.И.", 40,
                             "ACTIVE", "96.02", "Предоставление услуг парикмахерскими и салонами красоты", "Тестовая республика",
                             "Шаблонова Татьяна Ивановна", []),
        "FNS": fns("PATENT", 4, arrears=350000, taxes=120000),
        "FINANCIAL_STATEMENTS": None,
        "CREDIT_BUREAU": bki(history=30, loans=1, payments=25000, inq90=1),
        "BANK_TURNOVER": turnover(inflows(700000, NORMAL, 0.02)),
    }, [{"request_id": "X2", "application": app("EXPRESS", "INVENTORY", 800000, 12, 700000, 25000, IE)}])

    # X3: large clean LLC
    i = inn["X3"]
    add("X3", "EXTRA", "Крупная чистая ООО: одобрение с альтернативой кредитной линии и ручное рассмотрение крупной суммы", "client.demo", 150, {
        "REGISTRY": registry(i, "114001000801", "Общество с ограниченной ответственностью \"Прототип-Софт\"", "ООО \"Прототип-Софт\"", 150,
                             "ACTIVE", "62.01", "Разработка компьютерного программного обеспечения", "Синтетическая область",
                             "Черновиков Степан Алексеевич", [{"name": "Черновиков Степан Алексеевич", "share_percent": "100.00"}]),
        "FNS": fns("OSN", 140, sme="SMALL", taxes=21000000),
        "FINANCIAL_STATEMENTS": fs(400000000, 352000000, 46000000),
        "CREDIT_BUREAU": bki(history=120, loans=1, payments=1500000, inq90=0),
        "BANK_TURNOVER": turnover(inflows(34000000, STABLE, 0.12)),
    }, [
        {"request_id": "X3-WC-12M", "application": app("WORKING_CAPITAL", "CASH_GAP", 12000000, 24, 34000000, 1500000, LE)},
        {"request_id": "X3-WC-25M", "application": app("WORKING_CAPITAL", "CONTRACT_EXECUTION", 25000000, 24, 34000000, 1500000, LE)},
    ])

    # X4: IP without credit history
    i = inn["X4"]
    add("X4", "EXTRA", "ИП без кредитной истории: одобрение экспресс-кредита", "client.demo", 30, {
        "REGISTRY": registry(i, "32400200000901", "Индивидуальный предприниматель Макетов Петр Николаевич", "ИП Макетов П.Н.", 30,
                             "ACTIVE", "45.20", "Техническое обслуживание и ремонт автотранспортных средств", "Демонстрационная область",
                             "Макетов Петр Николаевич", []),
        "FNS": fns("USN_INCOME", 3, taxes=210000),
        "FINANCIAL_STATEMENTS": None,
        "CREDIT_BUREAU": {"no_record": True},
        "BANK_TURNOVER": turnover(inflows(900000, STABLE, 0.08)),
    }, [{"request_id": "X4", "application": app("EXPRESS", "EQUIPMENT", 500000, 12, 900000, 0, IE)}])

    # X5: IP without account in the bank: income not confirmed
    i = inn["X5"]
    add("X5", "EXTRA", "ИП без счета в банке: дозапрос выписки, затем ручная проверка документа", "client.demo", 28, {
        "REGISTRY": registry(i, "32400200001001", "Индивидуальный предприниматель Образцова Юлия Сергеевна", "ИП Образцова Ю.С.", 28,
                             "ACTIVE", "85.41", "Образование дополнительное детей и взрослых", "Условный край", "Образцова Юлия Сергеевна", []),
        "FNS": fns("USN_INCOME", 5, taxes=150000),
        "FINANCIAL_STATEMENTS": None,
        "CREDIT_BUREAU": bki(history=50, loans=0, payments=0, inq90=1),
        "BANK_TURNOVER": turnover(None),
    }, [
        {"request_id": "X5", "application": app("EXPRESS", "GENERAL_NEEDS", 700000, 12, 650000, 0, IE)},
        {"request_id": "X5-WITH-STATEMENT", "state": {"auto_info_request_count": 1, "bank_statement_attached": True},
         "application": app("EXPRESS", "GENERAL_NEEDS", 700000, 12, 650000, 0, IE),
         "note": "после ответа на дозапрос: приложена выписка BANK_STATEMENT"},
    ])

    # X6: weak LLC: low score
    i = inn["X6"]
    add("X6", "EXTRA", "Слабая ООО: отказ по грейду DCL_LOW_SCORE", "client.demo", 14, {
        "REGISTRY": registry(i, "125001001101", "Общество с ограниченной ответственностью \"Пробник-Тур\"", "ООО \"Пробник-Тур\"", 14,
                             "ACTIVE", "79.11", "Деятельность туристических агентств", "Тестовая республика", "Пробников Иван Иванович",
                             [{"name": "Пробников Иван Иванович", "share_percent": "100.00"}]),
        "FNS": fns("USN_INCOME", 3, taxes=40000),
        "FINANCIAL_STATEMENTS": {"found": False},
        "CREDIT_BUREAU": bki(history=10, loans=3, payments=95000, inq90=6, inq30=3, max12=20),
        "BANK_TURNOVER": turnover(inflows(450000, VOLATILE, -0.25)),
    }, [{"request_id": "X6", "application": app("EXPRESS", "CASH_GAP", 1000000, 12, 480000, 95000, LE)}])

    # X7: compliance red flag
    i = inn["X7"]
    add("X7", "EXTRA", "ООО с комплаенс-флагом: отказ без раскрытия причины (SF_COMPLIANCE)", "client.demo", 44, {
        "REGISTRY": registry(i, "123001001201", "Общество с ограниченной ответственностью \"Модель-Сервис\"", "ООО \"Модель-Сервис\"", 44,
                             "ACTIVE", "49.41", "Деятельность автомобильного грузового транспорта", "Синтетическая область",
                             "Набросков Алексей Петрович", [{"name": "Набросков Алексей Петрович", "share_percent": "100.00"}]),
        "FNS": fns("OSN", 18, taxes=900000),
        "FINANCIAL_STATEMENTS": fs(36000000, 33000000, 2100000),
        "CREDIT_BUREAU": bki(history=44, loans=1, payments=150000, inq90=1),
        "BANK_TURNOVER": turnover(inflows(3000000, STABLE, 0.05), compliance="RED"),
    }, [{"request_id": "X7", "application": app("EXPRESS", "INVENTORY", 1500000, 18, 3000000, 150000, LE)}])

    for c in out:
        assert inn_is_valid(c["inn"]), c["inn"]
        assert ogrn_is_valid(c["sources"]["REGISTRY"]["ogrn"]), c["sources"]["REGISTRY"]["ogrn"]
        assert c["inn"][:2] == "00"
    return out


NOT_FOUND_EXAMPLE_INN = complete_inn("009900001")

DEMO_PASSWORDS = {"CLIENT": "Demo-Client-2026", "UNDERWRITER": "Demo-Uw-2026", "RISK_MANAGER": "Demo-Risk-2026"}


def users(comps: list[dict]) -> list[dict]:
    by_login: dict[str, list[str]] = {}
    for c in comps:
        by_login.setdefault(c["client_login"], []).append(c["inn"])
    clients = [
        ("client.irina", "Примерова Ирина Олеговна", "OWNER", "P1 Ирина, ИП", ["S1"]),
        ("client.andrey", "Образцов Андрей Николаевич", "CEO", "P2 Андрей, директор ООО", ["S2"]),
        ("client.marina", "Шаблонова Марина Петровна", "CFO", "P3 Марина, финансовый директор ООО", ["S3"]),
        ("client.sergey", "Пробников Сергей Алексеевич", "OWNER", "P5 Сергей, начинающий ИП", ["S4"]),
        ("client.oleg", "Набросков Олег Павлович", "FINANCE_MANAGER", "P4 Олег, уполномоченный сотрудник", ["S5", "S5b"]),
        ("client.demo", "Тестов Демо Демович", "OTHER_AUTHORIZED", "учетная запись для свободной проверки жюри", ["EXTRA"]),
    ]
    out = []
    for login, name, role, persona, sc in clients:
        out.append({"login": login, "password": DEMO_PASSWORDS["CLIENT"], "role": "CLIENT", "full_name": name,
                    "representative_role": role, "persona": persona, "scenarios": sc, "company_inns": by_login.get(login, []),
                    "is_demo": True})
    out += [
        {"login": "uw.dmitry", "password": DEMO_PASSWORDS["UNDERWRITER"], "role": "UNDERWRITER", "full_name": "Эскизов Дмитрий Романович",
         "representative_role": None, "persona": "B1 Дмитрий, андеррайтер", "scenarios": ["S3", "S5b"], "company_inns": [], "is_demo": True},
        {"login": "uw.anna", "password": DEMO_PASSWORDS["UNDERWRITER"], "role": "UNDERWRITER", "full_name": "Черновикова Анна Павловна",
         "representative_role": None, "persona": "второй андеррайтер", "scenarios": ["гонка Взять в работу"], "company_inns": [], "is_demo": True},
        {"login": "risk.elena", "password": DEMO_PASSWORDS["RISK_MANAGER"], "role": "RISK_MANAGER", "full_name": "Шаблонова Елена Николаевна",
         "representative_role": None, "persona": "B2 Елена, риск-менеджер", "scenarios": ["S3", "метрики", "аудит"], "company_inns": [], "is_demo": True},
    ]
    return out
