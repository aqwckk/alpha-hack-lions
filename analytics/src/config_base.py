"""Static parts of the configs: product catalog, reason-code dictionary,
feature definitions. Calibrated numbers are filled in by src.model and
src.calibrate_policy."""

from __future__ import annotations

from .mockgen import OKVED_RISK_GROUPS

AS_OF = "2026-10-23"
POLICY_VERSION = "policy-2026.10-v1"
SCORECARD_VERSION = "scorecard-2026.10-v1"
AUTHOR = "analytics"

FEATURE_PARAMETERS = {
    "min_turnover_months": 6,
    "min_turnover_months_for_growth": 12,
    "okved_risk_groups": dict(sorted(OKVED_RISK_GROUPS.items())),
    "okved_default_group": "MEDIUM",
    "mass_registration_flags": ["MASS_ADDRESS", "MASS_DIRECTOR"],
}

# code, name for employees, source, type, candidate edges or categories, monotonic direction
# direction: "up" means higher value -> lower risk (higher WoE), "down" the opposite.
FACTOR_META = {
    "business_age_months": ("Возраст бизнеса, мес.", ["REGISTRY"], "numeric", [6, 12, 24, 36, 60, 120], "up"),
    "industry_risk_group": ("Отраслевая группа риска (ОКВЭД)", ["REGISTRY"], "categorical", ["LOW", "MEDIUM", "HIGH"], None),
    "confirmed_monthly_revenue": ("Подтвержденная выручка в месяц, руб.", ["BANK_TURNOVER", "FINANCIAL_STATEMENTS"], "numeric",
                                  [300000, 500000, 1000000, 2000000, 3000000, 5000000, 10000000, 20000000], "up"),
    "revenue_growth": ("Динамика выручки", ["BANK_TURNOVER", "FINANCIAL_STATEMENTS"], "numeric",
                       ["-0.30", "-0.15", "-0.05", "0", "0.05", "0.10", "0.20", "0.30"], "up"),
    "debt_load_ratio": ("Долговая нагрузка (платежи / выручка)", ["APPLICATION", "CREDIT_BUREAU", "BANK_TURNOVER", "FINANCIAL_STATEMENTS"], "numeric",
                        ["0.01", "0.05", "0.10", "0.15", "0.20", "0.30", "0.40", "0.60"], "down"),
    "bki_max_delinquency_days_12m": ("Максимальная просрочка за 12 мес., дней", ["CREDIT_BUREAU"], "numeric", [1, 6, 30, 60], "down"),
    "bki_inquiries_30d": ("Запросы в БКИ за 30 дней", ["CREDIT_BUREAU"], "numeric", [1, 2, 3], "down"),
    "bki_inquiries_90d": ("Запросы в БКИ за 90 дней", ["CREDIT_BUREAU"], "numeric", [1, 2, 3, 4, 6], "down"),
    "bki_credit_history_months": ("Длина кредитной истории, мес.", ["CREDIT_BUREAU"], "numeric", [6, 12, 24, 36, 60], "up"),
    "bki_active_loans_count": ("Число действующих кредитов", ["CREDIT_BUREAU"], "numeric", [1, 2, 3, 4], None),
    "tax_arrears_flag": ("Налоговая недоимка", ["FNS"], "categorical", ["NO", "YES"], None),
    "fns_mass_registration": ("Массовый адрес или руководитель", ["FNS"], "categorical", ["NO", "YES"], None),
    "turnover_volatility": ("Нестабильность оборотов (коэффициент вариации)", ["BANK_TURNOVER"], "numeric",
                            ["0.10", "0.15", "0.20", "0.25", "0.30", "0.40", "0.50"], "down"),
    "net_margin": ("Рентабельность по чистой прибыли", ["FINANCIAL_STATEMENTS"], "numeric",
                   ["-0.05", "0", "0.03", "0.06", "0.10", "0.15"], "up"),
    "employees_count": ("Среднесписочная численность", ["FNS"], "numeric", [1, 3, 5, 10, 20, 50], "up"),
    "applicant_type": ("Тип заявителя", ["APPLICATION"], "categorical", ["LEGAL_ENTITY", "INDIVIDUAL_ENTREPRENEUR"], None),
    "requested_amount_to_revenue": ("Запрошенная сумма / годовая выручка", ["APPLICATION"], "numeric",
                                    ["0.05", "0.10", "0.20", "0.30", "0.50"], "down"),
}

FEATURE_DEFINITIONS = {
    "business_age_months": "Полных календарных месяцев от REGISTRY.registration_date до as_of_date (дата скоринга). Нет данных, если субъект не найден.",
    "industry_risk_group": "Группа риска по первым двум цифрам REGISTRY.okved_main_code через feature_parameters.okved_risk_groups; класс, которого нет в справочнике, получает okved_default_group.",
    "confirmed_monthly_revenue": "BANK_TURNOVER.avg_monthly_inflow_12m, если has_account = true и months_available >= min_turnover_months; иначе FINANCIAL_STATEMENTS.revenue / 12 (до копеек), если found = true и revenue > 0; иначе нет данных. Выписка клиента (BANK_STATEMENT) в скоринге не используется.",
    "revenue_growth": "Если доступно не меньше min_turnover_months_for_growth месяцев оборотов: (сумма последних 6 мес. - сумма предыдущих 6 мес.) / сумма предыдущих 6 мес.; иначе (revenue - revenue_prev_year) / revenue_prev_year из ГИР БО; иначе нет данных. Округление 4 знака.",
    "debt_load_ratio": "existing_payments / income_for_dti, где existing_payments = max(анкета.existing_monthly_payments_declared, CREDIT_BUREAU.monthly_payments_total или 0 при no_record), income_for_dti = min(анкета.monthly_revenue_declared, confirmed_monthly_revenue) или заявленная выручка, если подтвержденной нет. Округление 4 знака.",
    "bki_max_delinquency_days_12m": "CREDIT_BUREAU.max_delinquency_days_12m; нет данных при no_record = true.",
    "bki_inquiries_30d": "CREDIT_BUREAU.inquiries_30d; нет данных при no_record = true.",
    "bki_inquiries_90d": "CREDIT_BUREAU.inquiries_90d; нет данных при no_record = true.",
    "bki_credit_history_months": "CREDIT_BUREAU.credit_history_months; нет данных при no_record = true.",
    "bki_active_loans_count": "CREDIT_BUREAU.active_loans_count; нет данных при no_record = true.",
    "tax_arrears_flag": "YES, если FNS.tax_arrears_amount > 0, иначе NO.",
    "fns_mass_registration": "YES, если FNS.unreliable_flags содержит MASS_ADDRESS или MASS_DIRECTOR, иначе NO.",
    "turnover_volatility": "Коэффициент вариации последних months_available значений BANK_TURNOVER.inflow_by_month: стандартное отклонение (по генеральной совокупности, деление на n) / среднее; только при months_available >= min_turnover_months. Округление 4 знака.",
    "net_margin": "FINANCIAL_STATEMENTS.net_profit / revenue (только ООО). Округление 4 знака.",
    "employees_count": "FNS.employees_count.",
    "applicant_type": "LEGAL_ENTITY (ИНН 10 цифр) или INDIVIDUAL_ENTREPRENEUR (12 цифр).",
    "requested_amount_to_revenue": "amount / (income_for_dti x 12). Округление 4 знака.",
}

PRODUCTS = {
    "EXPRESS": {
        "name": "Экспресс-кредит",
        "direct_application": True,
        "applicant_types": ["INDIVIDUAL_ENTREPRENEUR", "LEGAL_ENTITY"],
        "allowed_purposes": ["INVENTORY", "CASH_GAP", "CONTRACT_EXECUTION", "SEASONAL_PURCHASES", "EQUIPMENT", "REAL_ESTATE", "BUSINESS_EXPANSION", "GENERAL_NEEDS"],
        "amount_min": "300000.00", "amount_max": "5000000.00", "amount_step": "10000.00",
        "term_min_months": 6, "term_max_months": 36,
        "base_rate_percent": "22.00",
        "review_mode": "AUTO",
        "auto_approval_limit": "5000000.00",
        "green_grades": ["A", "B", "C"], "gray_grades": [], "decline_grades": ["D", "E"],
        "min_business_age_months": 6,
        "requires_owner_guarantee_for": ["LEGAL_ENTITY"],
        "requires_collateral": False, "min_collateral_coverage": None,
        "required_documents": [],
        "tranche_max_term_months": None,
    },
    "WORKING_CAPITAL": {
        "name": "Оборотный кредит",
        "direct_application": True,
        "applicant_types": ["INDIVIDUAL_ENTREPRENEUR", "LEGAL_ENTITY"],
        "allowed_purposes": ["INVENTORY", "CASH_GAP", "CONTRACT_EXECUTION", "SEASONAL_PURCHASES", "GENERAL_NEEDS"],
        "amount_min": "1000000.00", "amount_max": "30000000.00", "amount_step": "10000.00",
        "term_min_months": 3, "term_max_months": 36,
        "base_rate_percent": "19.00",
        "review_mode": "AUTO_WITH_MANUAL",
        "auto_approval_limit": "15000000.00",
        "green_grades": ["A", "B"], "gray_grades": ["C"], "decline_grades": ["D", "E"],
        "min_business_age_months": 12,
        "requires_owner_guarantee_for": ["LEGAL_ENTITY"],
        "requires_collateral": False, "min_collateral_coverage": None,
        "required_documents": [],
        "tranche_max_term_months": None,
    },
    "CREDIT_LINE": {
        "name": "Кредитная линия",
        "direct_application": False,
        "applicant_types": ["INDIVIDUAL_ENTREPRENEUR", "LEGAL_ENTITY"],
        "allowed_purposes": ["INVENTORY", "CASH_GAP", "CONTRACT_EXECUTION", "SEASONAL_PURCHASES"],
        "amount_min": "1000000.00", "amount_max": "30000000.00", "amount_step": "10000.00",
        "term_min_months": 12, "term_max_months": 36,
        "base_rate_percent": "20.00",
        "review_mode": "AUTO_WITH_MANUAL",
        "auto_approval_limit": "15000000.00",
        "green_grades": ["A", "B"], "gray_grades": ["C"], "decline_grades": ["D", "E"],
        "min_business_age_months": 12,
        "requires_owner_guarantee_for": ["LEGAL_ENTITY"],
        "requires_collateral": False, "min_collateral_coverage": None,
        "required_documents": [],
        "tranche_max_term_months": 12,
    },
    "INVESTMENT": {
        "name": "Инвестиционный кредит",
        "direct_application": True,
        "applicant_types": ["INDIVIDUAL_ENTREPRENEUR", "LEGAL_ENTITY"],
        "allowed_purposes": ["EQUIPMENT", "REAL_ESTATE", "BUSINESS_EXPANSION"],
        "amount_min": "5000000.00", "amount_max": "100000000.00", "amount_step": "10000.00",
        "term_min_months": 12, "term_max_months": 84,
        "base_rate_percent": "17.00",
        "review_mode": "MANUAL",
        "auto_approval_limit": "0.00",
        "green_grades": ["A", "B", "C"], "gray_grades": ["D"], "decline_grades": ["E"],
        "min_business_age_months": 24,
        "requires_owner_guarantee_for": ["LEGAL_ENTITY"],
        "requires_collateral": True, "min_collateral_coverage": "1.00",
        "required_documents": ["COLLATERAL_DOCUMENTS", "SUPPLIER_QUOTE"],
        "tranche_max_term_months": None,
    },
}

STOP_FACTORS = {
    "blocked_company_statuses": ["LIQUIDATING", "BANKRUPTCY", "REORGANIZING", "CEASED"],
    "unreliable_flags": ["UNRELIABLE_ADDRESS", "UNRELIABLE_DIRECTOR", "MASS_ADDRESS", "MASS_DIRECTOR", "DISQUALIFIED_DIRECTOR"],
    "current_delinquency_min_days": 30,
    "tax_arrears_stop_amount": "100000.00",
    "compliance_stop_flags": ["RED"],
}

REASON_CODES = {
    # 9.1 stop factors
    "SF_COMPANY_NOT_FOUND": ("POL-01", "DECLINED", "FULL",
        "Мы не нашли компанию или ИП с таким ИНН в государственном реестре.",
        "Проверьте ИНН и подайте новую заявку.",
        "ЕГРЮЛ/ЕГРИП: субъект с ИНН {inn} не найден."),
    "SF_COMPANY_STATUS": ("POL-01", "DECLINED", "FULL",
        "По данным госреестра компания (ИП) ликвидируется, проходит банкротство или реорганизацию, либо деятельность прекращена. В такой ситуации банк не выдает кредиты.",
        "Если сведения в реестре устарели, обновите их в налоговой и подайте заявку снова.",
        "Статус субъекта {company_status} входит в blocked_company_statuses."),
    "SF_BUSINESS_AGE": ("POL-01", "DECLINED", "FULL",
        "Этот продукт доступен бизнесу, который работает не меньше {min_business_age_months} месяцев. Ваш бизнес зарегистрирован {registration_date}.",
        "Подать заявку на этот продукт можно будет с {eligible_date}.",
        "Возраст бизнеса {business_age_months} мес. меньше минимума продукта {min_business_age_months} мес."),
    "SF_UNRELIABLE_REGISTRY_DATA": ("POL-01", "DECLINED", "FULL",
        "В госреестре есть отметка о недостоверности сведений о компании (например, об адресе или руководителе).",
        "Исправьте сведения в налоговой. После снятия отметки можно подать заявку снова.",
        "Признаки ФНС/ЕГРЮЛ: {flags}."),
    "SF_CURRENT_DELINQUENCY": ("POL-01", "DECLINED", "FULL",
        "По данным бюро кредитных историй у вас есть просроченная задолженность по действующему кредиту или займу.",
        "Погасите просроченную задолженность и подайте заявку снова. Свою кредитную историю можно бесплатно проверить в бюро кредитных историй.",
        "БКИ: текущая просрочка {delinquency_days} дн., сумма {delinquency_amount}; порог current_delinquency_min_days."),
    "SF_TAX_ARREARS": ("POL-01", "DECLINED", "FULL",
        "По данным налоговой у бизнеса есть задолженность по налогам.",
        "Погасите задолженность и подайте заявку снова после того, как сведения в налоговой обновятся.",
        "ФНС: недоимка {tax_arrears_amount} не меньше tax_arrears_stop_amount."),
    "SF_COMPLIANCE": ("POL-01", "DECLINED", "GENERIC",
        "Банк не может предложить финансирование по результатам обязательных проверок. Подробности таких проверок банк не раскрывает.",
        "Повторно обратиться в банк можно позже, подав новую заявку в кабинете.",
        "Комплаенс-флаг мока: {compliance_flag}. Причину клиенту не раскрывать."),
    # 9.2 declines
    "DCL_LOW_SCORE": ("POL-03", "DECLINED", "FULL",
        "По совокупности данных о бизнесе и кредитной истории банк сейчас не может выдать этот кредит.",
        "Чаще всего на решение влияют стабильность выручки, текущая долговая нагрузка и история платежей. Вернитесь после нескольких месяцев стабильной работы или рассмотрите меньшую сумму.",
        "Грейд {grade} входит в decline_grades продукта {product_code}."),
    "DCL_AFFORDABILITY": ("POL-07", "DECLINED", "FULL",
        "Платеж по кредиту даже на самых мягких условиях продукта оказался бы слишком большим для текущей выручки и уже имеющихся платежей бизнеса.",
        "Рассмотрите меньшую сумму или вернитесь, когда выручка вырастет или текущие кредиты будут погашены.",
        "Допустимый платеж {allowed_payment} не покрывает минимальные условия ни одного варианта."),
    # 9.3 counter-offer
    "CO_DEBT_LOAD": ("POL-07", "COUNTER_OFFER", "FULL",
        "Ежемесячный платеж на запрошенных условиях оказался бы слишком большим для текущей выручки и уже имеющихся платежей бизнеса. Поэтому банк предлагает меньшую сумму или более долгий срок: так платеж будет посильным.",
        None,
        "Запрошенный платеж {requested_payment} больше допустимого {allowed_payment} (грейд {grade})."),
    "CO_PRODUCT_ALTERNATIVE": ("POL-06, POL-07", "APPROVED, COUNTER_OFFER", "FULL",
        "Вам может подойти кредитная линия: деньги можно брать частями, когда они нужны, гасить и брать снова. Проценты начисляются только на ту сумму, которую вы взяли.",
        None,
        "Предложена кредитная линия как альтернативный продукт."),
    # 9.4 info request
    "NI_INCOME_NOT_CONFIRMED": ("POL-02", "NEEDS_INFO", "FULL",
        "Мы не смогли подтвердить выручку по данным банка и налоговой. Приложите выписку по расчетному счету в другом банке за последние 12 месяцев и проверьте сумму выручки в заявке.",
        None,
        "Нет источника подтверждения выручки: нет оборотов в банке и отчетности ГИР БО."),
    # 9.5 manual review
    "MR_PRODUCT_MANUAL_ONLY": ("POL-05", "MANUAL_REVIEW", "FULL", "Инвестиционные кредиты всегда рассматривает специалист.", None, "Продукт с режимом MANUAL."),
    "MR_AMOUNT_ABOVE_AUTO_LIMIT": ("POL-05", "MANUAL_REVIEW", "FULL", "Заявки на крупные суммы рассматривает специалист.", None, "Сумма {amount} больше auto_approval_limit продукта."),
    "MR_GRAY_ZONE": ("POL-05", "MANUAL_REVIEW", "NONE", None, None, "Грейд {grade} в серой зоне продукта."),
    "MR_DATA_MISMATCH": ("POL-05", "MANUAL_REVIEW", "NONE", None, None, "Заявленная выручка выше подтвержденной на {revenue_mismatch_pct}% (порог revenue_mismatch_threshold)."),
    "MR_TAX_ARREARS_MINOR": ("POL-05", "MANUAL_REVIEW", "NONE", None, None, "Недоимка {tax_arrears_amount} меньше порога отказа."),
    "MR_INCOME_DOCUMENT_CHECK": ("POL-05", "MANUAL_REVIEW", "NONE", None, None, "Доход подтвержден только выпиской клиента, нужна проверка документа."),
    "MR_COLLATERAL_REVIEW": ("POL-05", "MANUAL_REVIEW", "NONE", None, None, "Покрытие залогом {collateral_coverage} ниже min_collateral_coverage."),
    "MR_RETURNED_AFTER_INFO": ("POL-05", "MANUAL_REVIEW", "NONE", None, None, "Возврат после дозапроса андеррайтера, заявка закреплена за {assignee}."),
    "MR_INFO_CYCLES_EXCEEDED": ("POL-02", "MANUAL_REVIEW", "NONE", None, None, "Исчерпан лимит автоматических дозапросов."),
}


def reason_codes_dict() -> dict:
    out = {}
    for code, (rule, outcome, vis, client, step, emp) in REASON_CODES.items():
        out[code] = {
            "rule": rule,
            "outcome": outcome,
            "client_visibility": vis,
            "client_text": client,
            "client_next_step": step,
            "employee_text": emp,
        }
    return out


def base_policy() -> dict:
    """Policy skeleton; calibrated sections are replaced later."""
    return {
        "schema": "credit-policy",
        "schema_version": 1,
        "version": POLICY_VERSION,
        "effective_from": AS_OF,
        "author": AUTHOR,
        "description": "Кредитная политика POL-01...POL-07 для синтетического каталога МСП. Денежные значения строками с двумя знаками (рубли.копейки), доли строками с двумя-четырьмя знаками, ставки строками в процентах годовых с двумя знаками.",
        "formats": {
            "money": "строка, рубли с копейками, 2 знака после точки, Decimal(18,2)",
            "ratio": "строка, доля единицы (0.30 = 30%)",
            "rate_percent": "строка, проценты годовых, 2 знака (23.50 = 23,5% годовых)",
            "rounding": "Decimal prec=28; деньги ROUND_HALF_UP до 0.01; доли ROUND_HALF_UP до 0.0001; суммы вариантов вниз до amount_rounding",
        },
        "products": PRODUCTS,
        "stop_factors": STOP_FACTORS,
        "income": {
            "income_source_priority": ["BANK_TURNOVER", "FINANCIAL_STATEMENTS", "BANK_STATEMENT"],
            "min_turnover_months": 6,
            "revenue_mismatch_threshold": "0.30",
        },
        "max_debt_load_by_grade": {"A": "0.30", "B": "0.25", "C": "0.20", "D": "0.15", "E": "0.10"},
        "rate_premium_by_grade": {"A": "0.00", "B": "1.00", "C": "2.50", "D": "5.00", "E": "8.00"},
        "counter_offer": {
            "counter_offer_min_share": "0.30",
            "max_counter_options": 3,
            "amount_rounding": "10000.00",
            "option_order": ["AMOUNT_REDUCED", "TERM_EXTENDED", "PRODUCT_CHANGED"],
            "recommended_priority": ["TERM_EXTENDED", "AMOUNT_REDUCED", "PRODUCT_CHANGED"],
            "credit_line_product": "CREDIT_LINE",
            "credit_line_source_products": ["EXPRESS", "WORKING_CAPITAL"],
            "credit_line_suggest_purposes": ["SEASONAL_PURCHASES", "CASH_GAP"],
        },
        "authority": {
            "underwriter_authority_limit": "50000000.00",
            "override_requires_risk_approval": True,
        },
        "process": {
            "max_auto_info_cycles": 3,
            "offer_ttl_days": 7,
            "info_response_ttl_days": 14,
            "draft_ttl_days": 30,
            "manual_review_sla_hours": 8,
            "decision_sla_auto_minutes": 15,
            "decision_sla_manual_hours": 24,
        },
        "info_request_templates": {
            "NI_INCOME_NOT_CONFIRMED": [
                {"reason_code": "NI_INCOME_NOT_CONFIRMED", "answer_type": "DOCUMENT", "document_type": "BANK_STATEMENT", "field_name": None, "required": True},
                {"reason_code": "NI_INCOME_NOT_CONFIRMED", "answer_type": "FIELD", "document_type": None, "field_name": "monthly_revenue_declared", "required": True},
            ]
        },
        "rules": [
            {"id": "POL-01", "name": "Стоп-факторы", "terminal": True, "outcome": "DECLINED",
             "reason_codes": ["SF_COMPANY_NOT_FOUND", "SF_COMPANY_STATUS", "SF_BUSINESS_AGE", "SF_UNRELIABLE_REGISTRY_DATA", "SF_CURRENT_DELINQUENCY", "SF_TAX_ARREARS", "SF_COMPLIANCE"],
             "parameters": ["stop_factors.*", "products.*.min_business_age_months"]},
            {"id": "POL-02", "name": "Подтверждение дохода", "terminal": True, "outcome": "NEEDS_INFO или MANUAL_REVIEW",
             "reason_codes": ["NI_INCOME_NOT_CONFIRMED", "MR_INFO_CYCLES_EXCEEDED"],
             "parameters": ["income.income_source_priority", "income.min_turnover_months", "process.max_auto_info_cycles"]},
            {"id": "POL-03", "name": "Минимальный грейд", "terminal": True, "outcome": "DECLINED",
             "reason_codes": ["DCL_LOW_SCORE"], "parameters": ["products.*.decline_grades"]},
            {"id": "POL-04", "name": "Расчет долговой нагрузки", "terminal": False, "outcome": None, "reason_codes": [],
             "parameters": ["max_debt_load_by_grade", "rate_premium_by_grade", "products.*.base_rate_percent", "counter_offer.amount_rounding"]},
            {"id": "POL-05", "name": "Причины ручного рассмотрения", "terminal": True, "outcome": "MANUAL_REVIEW",
             "reason_codes": ["MR_PRODUCT_MANUAL_ONLY", "MR_AMOUNT_ABOVE_AUTO_LIMIT", "MR_GRAY_ZONE", "MR_DATA_MISMATCH", "MR_TAX_ARREARS_MINOR", "MR_INCOME_DOCUMENT_CHECK", "MR_COLLATERAL_REVIEW", "MR_RETURNED_AFTER_INFO"],
             "parameters": ["products.*.review_mode", "products.*.auto_approval_limit", "products.*.gray_grades", "income.revenue_mismatch_threshold", "stop_factors.tax_arrears_stop_amount", "products.*.min_collateral_coverage"]},
            {"id": "POL-06", "name": "Одобрение", "terminal": True, "outcome": "APPROVED",
             "reason_codes": ["CO_PRODUCT_ALTERNATIVE"], "parameters": ["counter_offer.credit_line_suggest_purposes"]},
            {"id": "POL-07", "name": "Контрпредложение", "terminal": True, "outcome": "COUNTER_OFFER или DECLINED",
             "reason_codes": ["CO_DEBT_LOAD", "CO_PRODUCT_ALTERNATIVE", "DCL_AFFORDABILITY"], "parameters": ["counter_offer.*"]},
        ],
        "reason_codes": reason_codes_dict(),
    }
