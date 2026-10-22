"""Reference texts shown to users (docs/product/*, docs/process/*). Kept on the backend, not in the frontend.

Reason codes of the policy come from policy.v1.json (reason_codes); codes that only an underwriter,
the completeness check or the cancellation logic assign are completed here from decision-model.md.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

MSK = ZoneInfo("Europe/Moscow")

PURPOSES: dict[str, dict[str, str]] = {
    "INVENTORY": {"title": "Закупить товар, сырье или материалы", "hint": "Например, партия товара к сезону или сырье для производства"},
    "CASH_GAP": {"title": "Закрыть кассовый разрыв", "hint": "Покупатели платят с отсрочкой, а платить поставщикам и зарплату нужно сейчас"},
    "CONTRACT_EXECUTION": {"title": "Выполнить контракт или крупный заказ", "hint": "Нужны деньги на исполнение, а оплата придет после сдачи работ"},
    "SEASONAL_PURCHASES": {"title": "Регулярные или сезонные закупки", "hint": "Деньги нужны несколько раз в год, и их можно возвращать после продаж"},
    "EQUIPMENT": {"title": "Купить оборудование или транспорт", "hint": "Станок, кофемашина, автомобиль для доставки"},
    "REAL_ESTATE": {"title": "Купить или отремонтировать помещение", "hint": "Офис, склад, торговая точка"},
    "BUSINESS_EXPANSION": {"title": "Открыть новую точку или направление", "hint": "Вложения, которые окупятся не сразу"},
    "GENERAL_NEEDS": {"title": "Другие нужды бизнеса", "hint": "Если задача не подходит ни под один вариант"},
}

PRODUCT_TEXTS: dict[str, dict[str, str]] = {
    "EXPRESS": {
        "description": "Быстрые деньги на любые нужды бизнеса без залога",
        "decision_speed": "Решение за несколько минут",
    },
    "WORKING_CAPITAL": {
        "description": "Пополнить оборотные средства: закупки, кассовые разрывы, контракты",
        "decision_speed": "До 15 минут; до 1 рабочего дня, если нужен специалист",
    },
    "CREDIT_LINE": {
        "description": "Лимит, из которого можно брать деньги частями и повторно",
        "decision_speed": "Вместе с основной заявкой",
    },
    "INVESTMENT": {
        "description": "Крупные вложения в оборудование, помещения, новые направления",
        "decision_speed": "До 1 рабочего дня после получения всех документов",
    },
}

DOCUMENT_TYPES: dict[str, dict[str, str]] = {
    "COLLATERAL_DOCUMENTS": {"title": "Документы на имущество в залог", "purpose": "подтвердить, что имущество существует и принадлежит залогодателю"},
    "SUPPLIER_QUOTE": {"title": "Договор или коммерческое предложение поставщика", "purpose": "понять, на что пойдут деньги и сколько стоит объект"},
    "CONTRACT_COPY": {"title": "Копия контракта с заказчиком", "purpose": "оценить, когда придут деньги по контракту"},
    "BANK_STATEMENT": {"title": "Выписка по расчетному счету в другом банке за 12 месяцев", "purpose": "подтвердить выручку, если ее не видно по данным банка и налоговой"},
    "COLLATERAL_VALUATION": {"title": "Отчет об оценке залога", "purpose": "определить рыночную стоимость залога"},
    "EXPLANATION_LETTER": {"title": "Пояснение (в свободной форме)", "purpose": "объяснить расхождение или особенность"},
    "OTHER": {"title": "Другой документ", "purpose": "ответить на вопрос банка"},
}

CONSENT_TEXTS: dict[str, dict[str, Any]] = {
    "CONSENT_PERSONAL_DATA": {
        "title": "Согласие на обработку персональных данных",
        "short_text": "Разрешаю банку обрабатывать персональные данные, указанные в заявке и полученные из госреестров (ФИО предпринимателя, руководителя, учредителей, поручителя), чтобы рассмотреть заявку и оформить кредит.",
        "full_text": (
            "Я даю согласие банку на обработку персональных данных, указанных в заявке и полученных банком из "
            "государственных реестров: фамилии, имени, отчества предпринимателя, руководителя, учредителей и поручителя, "
            "ИНН индивидуального предпринимателя. Цель обработки: рассмотрение заявки на кредит и оформление кредита. "
            "Действия с данными: сбор, запись, хранение, уточнение, использование, передача в бюро кредитных историй "
            "в объеме согласия на запрос кредитной истории. Срок действия: до достижения цели обработки. "
            "Согласие можно отозвать, отменив заявку в кабинете. Прототип: все данные синтетические."
        ),
        "version": "PD-2026-10-v1",
        "ttl_days": None,
    },
    "CONSENT_CREDIT_BUREAU": {
        "title": "Согласие на запрос кредитной истории",
        "short_text": "Разрешаю банку запросить мою (компании) кредитную историю в бюро кредитных историй, чтобы оценить заявку. Банк увидит действующие и закрытые кредиты, платежи и просрочки.",
        "full_text": (
            "Я даю согласие банку на получение кредитного отчета обо мне (о компании) из бюро кредитных историй "
            "для оценки заявки на кредит. Банк увидит действующие и закрытые кредиты, ежемесячные платежи, "
            "просрочки и число запросов кредитной истории. Согласие действует 6 месяцев с момента предоставления. "
            "Без этого согласия банк не запрашивает кредитную историю. Прототип: бюро кредитных историй смоделировано."
        ),
        "version": "BKI-2026-10-v1",
        "ttl_days": 183,
    },
    "AUTHORITY_CONFIRMATION": {
        "title": "Подтверждение полномочий",
        "short_text": "Подтверждаю, что могу действовать от имени компании (ИП): подавать заявку, давать согласия и подписывать документы.",
        "full_text": (
            "Я подтверждаю, что являюсь индивидуальным предпринимателем или уполномочен действовать от имени компании: "
            "подавать заявку на кредит, давать согласия и подписывать кредитные документы. Подтверждение действует "
            "на время рассмотрения и оформления заявки."
        ),
        "version": "AUTH-2026-10-v1",
        "ttl_days": None,
    },
}


def consent_text_sha256(consent_type: str) -> str:
    return hashlib.sha256(CONSENT_TEXTS[consent_type]["full_text"].encode("utf-8")).hexdigest()


EXTRA_REASON_CODES: dict[str, dict[str, Any]] = {
    "DCL_DATA_NOT_CONFIRMED": {
        "rule": "MANUAL", "outcome": "DECLINED", "client_visibility": "FULL",
        "client_text": "Сведения из заявки не подтвердились данными источников и документами.",
        "client_next_step": "Проверьте данные о выручке и подайте новую заявку с актуальными сведениями.",
        "employee_text": "Расхождение анкеты и источников не объяснено или пояснение не принято.",
    },
    "DCL_INSUFFICIENT_COLLATERAL": {
        "rule": "MANUAL", "outcome": "DECLINED", "client_visibility": "FULL",
        "client_text": "Предложенного залога недостаточно для запрошенной суммы.",
        "client_next_step": "Рассмотрите меньшую сумму или дополнительный залог.",
        "employee_text": "Покрытие залогом ниже требования продукта.",
    },
    "DCL_DOCUMENTS_NOT_PROVIDED": {
        "rule": "MANUAL", "outcome": "DECLINED", "client_visibility": "FULL",
        "client_text": "Банк не получил документы, без которых нельзя принять решение.",
        "client_next_step": "Подайте новую заявку и приложите документы из списка.",
        "employee_text": "Обязательные документы не предоставлены после дозапросов.",
    },
    "DCL_UNDERWRITER_RISK": {
        "rule": "MANUAL", "outcome": "DECLINED", "client_visibility": "FULL",
        "client_text": "После рассмотрения специалистом банк не может выдать кредит на запрошенных условиях.",
        "client_next_step": "Вы можете подать заявку на меньшую сумму или вернуться через несколько месяцев.",
        "employee_text": "Иной риск по экспертной оценке; подробности в обязательном комментарии.",
    },
    "CO_UNDERWRITER_TERMS": {
        "rule": "MANUAL", "outcome": "COUNTER_OFFER", "client_visibility": "FULL",
        "client_text": "Специалист банка подобрал условия с учетом особенностей вашей заявки.",
        "client_next_step": None,
        "employee_text": "Условия заданы андеррайтером, см. комментарий.",
    },
    "NI_MISSING_DOCUMENTS": {
        "rule": "COMPLETENESS", "outcome": "NEEDS_INFO", "client_visibility": "FULL",
        "client_text": "Не хватает документа \"{document_name}\". Он нужен, чтобы {document_purpose}.",
        "client_next_step": None,
        "employee_text": "Нет обязательного документа продукта: {document_type}.",
    },
    "NI_DATA_MISMATCH_EXPLANATION": {
        "rule": "MANUAL", "outcome": "NEEDS_INFO", "client_visibility": "FULL",
        "client_text": "Выручка в заявке отличается от данных налоговой отчетности. Уточните выручку или поясните разницу (например, рост продаж в этом году или выручка другой компании группы).",
        "client_next_step": None,
        "employee_text": "Расхождение заявленной и подтвержденной выручки.",
    },
    "NI_COLLATERAL_DOCUMENTS": {
        "rule": "MANUAL", "outcome": "NEEDS_INFO", "client_visibility": "FULL",
        "client_text": "Нужны документы по залогу: {document_name}. По ним банк оценит, какую часть кредита может обеспечить залог.",
        "client_next_step": None,
        "employee_text": "Нужны документы по объекту залога для оценки покрытия.",
    },
    "NI_OTHER": {
        "rule": "MANUAL", "outcome": "NEEDS_INFO", "client_visibility": "FULL",
        "client_text": "{question_text}",
        "client_next_step": None,
        "employee_text": "Произвольный вопрос андеррайтера.",
    },
    "TECH_SOURCE_UNAVAILABLE": {
        "rule": "TECH", "outcome": None, "client_visibility": "NONE", "client_text": None, "client_next_step": None,
        "employee_text": "Внешний источник {source} не ответил после всех повторов; последний код ошибки {last_error_code}.",
    },
    "TECH_PROCESSING_FAILED": {
        "rule": "TECH", "outcome": None, "client_visibility": "NONE", "client_text": None, "client_next_step": None,
        "employee_text": "Непредвиденная ошибка на этапе {failed_stage}; подробности в журнале по correlation_id.",
    },
    "CL_WITHDRAWN": {
        "rule": "CANCEL", "outcome": None, "client_visibility": "FULL", "client_text": "Вы отменили заявку.", "client_next_step": None,
        "employee_text": "Заявка отозвана клиентом.",
    },
    "CL_DRAFT_EXPIRED": {
        "rule": "CANCEL", "outcome": None, "client_visibility": "FULL",
        "client_text": "Черновик удален, потому что не изменялся {draft_ttl_days} дней.", "client_next_step": None,
        "employee_text": "Черновик закрыт по таймеру.",
    },
    "CL_INFO_TIMEOUT": {
        "rule": "CANCEL", "outcome": None, "client_visibility": "FULL",
        "client_text": "Заявка закрыта, потому что ответ на запрос банка не поступил до {due_at}.", "client_next_step": None,
        "employee_text": "Нет ответа на дозапрос в срок.",
    },
}

OFFER_DECLINE_REASONS: dict[str, str] = {
    "OD_RATE_TOO_HIGH": "Слишком высокая ставка",
    "OD_PAYMENT_TOO_HIGH": "Слишком большой ежемесячный платеж",
    "OD_AMOUNT_TOO_LOW": "Сумма меньше, чем нужно",
    "OD_FOUND_ELSEWHERE": "Нашел финансирование в другом месте",
    "OD_NOT_NEEDED": "Деньги больше не нужны",
    "OD_OTHER": "Другое",
}

MANUAL_DECLINE_CODES = (
    "SF_COMPANY_NOT_FOUND", "SF_COMPANY_STATUS", "SF_BUSINESS_AGE", "SF_UNRELIABLE_REGISTRY_DATA",
    "SF_CURRENT_DELINQUENCY", "SF_TAX_ARREARS", "SF_COMPLIANCE",
    "DCL_LOW_SCORE", "DCL_DATA_NOT_CONFIRMED", "DCL_INSUFFICIENT_COLLATERAL", "DCL_DOCUMENTS_NOT_PROVIDED", "DCL_UNDERWRITER_RISK",
)

UNDERWRITER_INFO_CODES = ("NI_MISSING_DOCUMENTS", "NI_DATA_MISMATCH_EXPLANATION", "NI_COLLATERAL_DOCUMENTS", "NI_OTHER", "NI_INCOME_NOT_CONFIRMED")

FIELD_LABELS: dict[str, str] = {
    "product_code": "Продукт",
    "purpose": "Задача, на которую нужны деньги",
    "amount": "Сумма кредита",
    "term_months": "Срок",
    "applicant_inn": "ИНН компании или ИП",
    "representative_role": "Кем вы являетесь в компании",
    "monthly_revenue_declared": "Средняя выручка в месяц за последние 12 месяцев",
    "existing_monthly_payments_declared": "Платежи по кредитам и займам в месяц",
    "owner_guarantee_agreed": "Поручительство собственника",
    "collateral_type": "Что предлагаете в залог",
    "collateral_description": "Описание залога",
    "collateral_value": "Примерная стоимость залога",
    "collateral_owner": "Чье это имущество",
    "investment_project_description": "О проекте",
    "own_contribution_amount": "Собственные средства",
    "client_comment": "Что еще важно знать банку",
}

# fields a client may change when an info request item of type FIELD asks for it
INFO_REQUEST_FIELDS = (
    "monthly_revenue_declared", "existing_monthly_payments_declared", "collateral_value", "collateral_description",
    "collateral_type", "collateral_owner", "investment_project_description", "own_contribution_amount", "client_comment",
)

VALIDATION_MESSAGES: dict[str, str] = {
    "REQUIRED": "Заполните это поле",
    "INVALID_FORMAT": "Проверьте формат: {hint}",
    "INN_LENGTH": "ИНН компании состоит из 10 цифр, ИНН ИП из 12 цифр",
    "INN_CHECKSUM": "В ИНН ошибка: проверьте цифры",
    "INN_NOT_FOUND": "Компания или ИП с таким ИНН не найдены в госреестре. Проверьте ИНН",
    "OUT_OF_RANGE": "Для этого продукта допустимо от {min} до {max}",
    "NOT_MULTIPLE_OF_STEP": "Сумма должна быть кратна {step} руб.",
    "PURPOSE_NOT_ALLOWED": "Этот продукт не подходит для выбранной задачи. Вернитесь к подбору",
    "CONSENT_REQUIRED": "Без этого согласия банк не сможет рассмотреть заявку",
    "GUARANTEE_REQUIRED": "Для компаний этот кредит выдается с поручительством собственника",
    "DOCUMENT_TYPE_NOT_ALLOWED": "Можно загрузить PDF, JPG или PNG",
    "DOCUMENT_TOO_LARGE": "Файл больше 10 МБ. Сожмите его или разделите на части",
    "DUPLICATE_ACTIVE_APPLICATION": "У вас уже есть заявка на этот продукт по этой компании. Продолжите ее или отмените",
    "APPLICANT_TYPE_NOT_ALLOWED": "Этот продукт недоступен для вашего типа бизнеса",
    "PAYMENTS_ABOVE_REVENUE": "Проверьте сумму: платежи больше выручки",
}

CLIENT_STATUS_TEXTS: dict[str, dict[str, str]] = {
    "FILLING": {"title": "Черновик заявки", "what": "Вы заполняете заявку. Все, что вы ввели, сохраняется автоматически.", "next": "Заполните оставшиеся поля и отправьте заявку. Осталось шагов: {n}.", "eta": "Обычно 5 минут"},
    "SENT": {"title": "Заявка отправлена", "what": "Мы получили заявку и проверяем, что все нужные сведения и документы на месте.", "next": "Если чего-то не хватает, мы попросим это здесь. Иначе начнем проверку данных.", "eta": "До 1 минуты"},
    "CHECKING": {"title": "Проверяем данные", "what": "Мы сверяем сведения о вашем бизнесе с госреестрами, налоговой и бюро кредитных историй и оцениваем заявку. От вас ничего не нужно.", "next": "Решение появится на этой странице.", "eta": "Обычно до 5 минут"},
    "CHECKING_DELAYED": {"title": "Проверяем данные", "what": "Один из источников данных сейчас отвечает с задержкой. Мы автоматически повторим запрос, заявка не потеряется. От вас ничего не нужно.", "next": "Как только источник ответит, проверка продолжится.", "eta": "До 20 минут"},
    "CHECKING_ERROR": {"title": "Проверяем данные", "what": "Проверка заняла больше времени, чем обычно. Сотрудник банка уже разбирается, от вас ничего не нужно.", "next": "Мы продолжим рассмотрение и покажем результат здесь.", "eta": "До 4 часов"},
    "ACTION_REQUIRED": {"title": "Нужны данные от вас", "what": "Чтобы продолжить рассмотрение, банку нужно {k_text}. Список ниже, по каждому пункту указано, зачем он нужен.", "next": "Ответьте на все пункты и нажмите \"Отправить ответ\". После этого рассмотрение продолжится автоматически.", "eta": "Ответить до {due}, иначе заявка будет закрыта"},
    "SPECIALIST_REVIEW": {"title": "Заявку рассматривает специалист", "what": "Ваша заявка требует внимательного рассмотрения, например из-за суммы или особенностей продукта. Ее изучает кредитный специалист банка.", "next": "Специалист примет решение или попросит уточнения здесь, в кабинете.", "eta": "Решение до {due}"},
    "DECISION_READY_APPROVED": {"title": "Заявка одобрена", "what": "Банк готов выдать кредит на условиях, которые вы просили.", "next": "Проверьте условия и график платежей, затем нажмите \"Принять условия\".", "eta": "Предложение действует до {due}"},
    "DECISION_READY_COUNTER": {"title": "Банк предлагает другие условия", "what": "Банк готов выдать кредит, но не на всех запрошенных условиях. Ниже ваш запрос и варианты, которые банк может предложить, и объяснение почему.", "next": "Выберите подходящий вариант или откажитесь от предложения.", "eta": "Предложение действует до {due}"},
    "DOCUMENTS": {"title": "Подписание документов", "what": "Мы готовим договор по выбранным условиям. Когда документы будут готовы, их можно будет прочитать и подписать здесь кодом подтверждения.", "next": "Ознакомьтесь с документами, получите код на экране и введите его.", "eta": "Подписать до {due}"},
    "DOCUMENTS_ERROR": {"title": "Подписание документов", "what": "Подготовка документов заняла больше времени, чем обычно. Сотрудник банка уже разбирается, от вас ничего не нужно.", "next": "Как только документы будут готовы, их можно будет подписать здесь.", "eta": "До 4 часов"},
    "PAYOUT": {"title": "Выдаем кредит", "what": "Документы подписаны. Банк перечисляет деньги на ваш расчетный счет (или открывает лимит кредитной линии).", "next": "Ничего делать не нужно, статус обновится автоматически.", "eta": "Обычно до 1 минуты"},
    "PAYOUT_ERROR": {"title": "Выдаем кредит", "what": "Выдача заняла больше времени, чем обычно. Сотрудник банка уже разбирается, от вас ничего не нужно.", "next": "Статус обновится автоматически.", "eta": "До 4 часов"},
    "COMPLETED": {"title": "Кредит выдан", "what": "Деньги перечислены на счет {account}.", "next": "Первый платеж {monthly_payment} нужно внести {first_payment_date}. График платежей доступен на этой странице.", "eta": ""},
    "COMPLETED_LINE": {"title": "Лимит кредитной линии открыт", "what": "Лимит {limit} открыт, деньги можно брать частями на счет {account}.", "next": "Если взять весь лимит на 12 месяцев, платеж составит {monthly_payment} в месяц. Первый платеж {first_payment_date}.", "eta": ""},
    "REJECTED": {"title": "Банк не может выдать кредит", "what": "{reason}", "next": "{next_step}", "eta": ""},
    "WITHDRAWN": {"title": "Заявка закрыта", "what": "Заявка отменена вами или закрыта, потому что ответ на запрос банка не поступил вовремя.", "next": "Вы можете подать новую заявку, данные компании подставятся автоматически.", "eta": ""},
    "EXPIRED": {"title": "Срок предложения истек", "what": "Вы не приняли или не подписали предложение до {due}.", "next": "Подайте новую заявку: условия будут рассчитаны заново по актуальным данным.", "eta": ""},
}

PROGRESS_STEPS = ("Заявка", "Отправлена", "Проверка данных", "Рассмотрение специалистом", "Решение", "Подписание", "Выдача", "Готово")

NOTIFICATIONS: dict[str, tuple[str, str]] = {
    "NTF_SUBMITTED": ("Заявка отправлена", "Заявка {application_number} принята. Мы проверяем данные, это обычно занимает несколько минут."),
    "NTF_CHECK_DELAYED": ("Проверка займет чуть больше времени", "Один из источников данных отвечает с задержкой. Мы повторим запрос автоматически, от вас ничего не нужно."),
    "NTF_INFO_REQUESTED": ("Нужны данные от вас", "Чтобы продолжить рассмотрение заявки {application_number}, ответьте на {k_text} до {due_at}."),
    "NTF_REVIEW_STARTED": ("Заявку рассматривает специалист", "Специалист банка начал рассмотрение. Решение до {review_due_at}."),
    "NTF_DECISION_APPROVED": ("Заявка одобрена", "Банк готов выдать {amount} на {term} мес. Примите условия до {expires_at}."),
    "NTF_DECISION_COUNTER_OFFER": ("Банк предлагает другие условия", "Посмотрите варианты и выберите подходящий до {expires_at}."),
    "NTF_DECISION_DECLINED": ("Решение по заявке", "К сожалению, банк не может выдать кредит. Причина и что можно сделать указаны в заявке."),
    "NTF_OFFER_EXPIRING": ("Предложение скоро истечет", "Предложение по заявке {application_number} действует до {expires_at}."),
    "NTF_OFFER_EXPIRED": ("Срок предложения истек", "Вы можете подать новую заявку, данные компании подставятся автоматически."),
    "NTF_DOCUMENTS_READY": ("Документы готовы к подписанию", "Проверьте договор и график платежей и подпишите их кодом подтверждения."),
    "NTF_SIGNING_CODE": ("Код подтверждения", "Ваш код: {code}. Действует 5 минут. Никому его не сообщайте. (В реальном продукте код приходил бы по защищенному каналу; в прототипе показывается здесь.)"),
    "NTF_LOAN_ISSUED": ("Кредит выдан", "{amount} перечислены на счет {account_masked}. Первый платеж {first_payment_date}."),
    "NTF_LIMIT_OPENED": ("Лимит кредитной линии открыт", "Лимит {amount} открыт на счете {account_masked}. Деньги можно брать частями."),
    "NTF_APPLICATION_CLOSED": ("Заявка закрыта", "Мы не получили ответ на запрос до {due_at}, поэтому заявка закрыта. Вы можете подать новую."),
    "NTF_EMP_INFO_PROVIDED": ("Клиент ответил на дозапрос", "Клиент ответил на дозапрос по заявке {application_number}."),
    "NTF_EMP_APPROVAL_REQUESTED": ("Нужна проверка решения", "Нужна проверка решения по заявке {application_number} (сумма {amount})."),
    "NTF_EMP_DECISION_RETURNED": ("Решение возвращено", "Риск-менеджер вернул решение по заявке {application_number}: {comment_preview}."),
    "NTF_EMP_PROCESSING_ERROR": ("Ошибка обработки", "Заявка {application_number} требует внимания: ошибка на этапе {failed_stage}."),
}

SIGNING_CODE_EXPIRED_TEXT = "Код больше не действует."

MONTHS_GENITIVE = ("января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря")


def today_msk():
    """Business date of the bank (Moscow): business age, schedules and as_of_date use it."""
    return datetime.now(MSK).date()


def fmt_dt(value: datetime | None) -> str:
    """'24 октября, 18:00' in Moscow time."""
    if value is None:
        return ""
    local = value.astimezone(MSK)
    return f"{local.day} {MONTHS_GENITIVE[local.month - 1]}, {local:%H:%M}"


def fmt_date(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        from datetime import date

        value = date.fromisoformat(value)
    return f"{value.day} {MONTHS_GENITIVE[value.month - 1]} {value.year}"


def fmt_money(value) -> str:
    if value is None:
        return ""
    whole, _, frac = f"{Decimal(str(value)):.2f}".partition(".")
    sign = "-" if whole.startswith("-") else ""
    whole = whole.lstrip("-")
    groups = []
    while whole:
        groups.insert(0, whole[-3:])
        whole = whole[:-3]
    text = " ".join(groups)
    return f"{sign}{text} руб." if frac == "00" else f"{sign}{text},{frac} руб."


def plural_ru(n: int, one: str, few: str, many: str) -> str:
    """Russian plural form for a count: 1 вопрос, 3 вопроса, 5 вопросов."""
    n_abs = abs(n)
    if n_abs % 10 == 1 and n_abs % 100 != 11:
        word = one
    elif 2 <= n_abs % 10 <= 4 and not 12 <= n_abs % 100 <= 14:
        word = few
    else:
        word = many
    return f"{n} {word}"


class _SafeDict(dict):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def _humanize(key: str, value: Any) -> Any:
    # Russian number format for percents and lower-case names inside a sentence.
    if key.endswith("_pct"):
        return str(value).replace(".", ",")
    if key == "document_name" and isinstance(value, str) and len(value) > 1 and value[1].islower():
        return value[0].lower() + value[1:]
    return value


def render(template: str | None, values: dict[str, Any]) -> str | None:
    if template is None:
        return None
    return template.format_map(_SafeDict({k: _humanize(k, v) for k, v in values.items() if v is not None}))
