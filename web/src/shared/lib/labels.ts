import type { ClientStatus } from '@/shared/api/types';

export type Tone = 'gray' | 'blue' | 'orange' | 'violet' | 'teal' | 'green' | 'red' | 'cyan';

export interface ClientStatusMeta {
  label: string;
  tone: Tone;
  /** The system is working, the client only waits: faster polling and "nothing needed" text. */
  waiting: boolean;
  terminal: boolean;
}

export const CLIENT_STATUS: Record<ClientStatus, ClientStatusMeta> = {
  FILLING: { label: 'Черновик', tone: 'gray', waiting: false, terminal: false },
  SENT: { label: 'Отправлена', tone: 'blue', waiting: true, terminal: false },
  CHECKING: { label: 'Проверяем данные', tone: 'blue', waiting: true, terminal: false },
  ACTION_REQUIRED: { label: 'Нужны данные от вас', tone: 'orange', waiting: false, terminal: false },
  SPECIALIST_REVIEW: { label: 'Рассматривает специалист', tone: 'violet', waiting: false, terminal: false },
  DECISION_READY: { label: 'Решение готово', tone: 'teal', waiting: false, terminal: false },
  DOCUMENTS: { label: 'Подписание документов', tone: 'cyan', waiting: true, terminal: false },
  PAYOUT: { label: 'Выдаем кредит', tone: 'blue', waiting: true, terminal: false },
  COMPLETED: { label: 'Кредит выдан', tone: 'green', waiting: false, terminal: true },
  REJECTED: { label: 'Отказ', tone: 'red', waiting: false, terminal: true },
  WITHDRAWN: { label: 'Заявка закрыта', tone: 'gray', waiting: false, terminal: true },
  EXPIRED: { label: 'Срок истек', tone: 'gray', waiting: false, terminal: true },
};

export function clientStatusMeta(status: string): ClientStatusMeta {
  return (CLIENT_STATUS as Record<string, ClientStatusMeta | undefined>)[status] ?? { label: status, tone: 'gray', waiting: false, terminal: false };
}

/** Polling interval from the status (docs/product/screens.md, section 1, rule 4). */
export function pollInterval(status: string | undefined): number | false {
  if (!status) return false;
  const meta = clientStatusMeta(status);
  if (meta.terminal) return false;
  return meta.waiting ? 3000 : 15000;
}

export const INTERNAL_STATUS: Record<string, { label: string; tone: Tone }> = {
  DRAFT: { label: 'Черновик', tone: 'gray' },
  SUBMITTED: { label: 'Отправлена, проверка полноты', tone: 'blue' },
  INFO_REQUESTED: { label: 'Дозапрос у клиента', tone: 'orange' },
  ENRICHMENT: { label: 'Обогащение из источников', tone: 'blue' },
  EXTERNAL_SERVICE_UNAVAILABLE: { label: 'Источник недоступен, повтор', tone: 'orange' },
  SCORING: { label: 'Скоринг', tone: 'blue' },
  DECISIONING: { label: 'Кредитная политика', tone: 'blue' },
  MANUAL_REVIEW: { label: 'В очереди на рассмотрение', tone: 'violet' },
  IN_REVIEW: { label: 'В работе у андеррайтера', tone: 'violet' },
  PENDING_RISK_APPROVAL: { label: 'На согласовании (4 глаза)', tone: 'orange' },
  OFFER_PENDING: { label: 'Предложение у клиента', tone: 'teal' },
  OFFER_ACCEPTED: { label: 'Предложение принято', tone: 'teal' },
  SIGNING: { label: 'Подписание', tone: 'cyan' },
  SIGNED: { label: 'Подписано, выдача', tone: 'cyan' },
  PROCESSING_ERROR: { label: 'Ошибка обработки', tone: 'red' },
  ISSUED: { label: 'Выдан', tone: 'green' },
  DECLINED: { label: 'Отказ', tone: 'red' },
  OFFER_DECLINED: { label: 'Клиент отказался', tone: 'gray' },
  OFFER_EXPIRED: { label: 'Предложение истекло', tone: 'gray' },
  CANCELLED: { label: 'Отменена', tone: 'gray' },
};

export function internalStatus(status: string): { label: string; tone: Tone } {
  return INTERNAL_STATUS[status] ?? { label: status, tone: 'gray' };
}

export const PRODUCT_NAMES: Record<string, string> = {
  EXPRESS: 'Экспресс-кредит',
  WORKING_CAPITAL: 'Оборотный кредит',
  CREDIT_LINE: 'Кредитная линия',
  INVESTMENT: 'Инвестиционный кредит',
};

export function productName(code: string | null | undefined): string {
  if (!code) return 'не указан';
  return PRODUCT_NAMES[code] ?? code;
}

export const SOURCE_LABELS: Record<string, string> = {
  REGISTRY: 'ЕГРЮЛ / ЕГРИП',
  FNS: 'ФНС: "Прозрачный бизнес"',
  FINANCIAL_STATEMENTS: 'ГИР БО: бухгалтерская отчетность',
  CREDIT_BUREAU: 'Бюро кредитных историй',
  BANK_TURNOVER: 'Обороты по счету в банке',
  EDO: 'ЭДО: подписание',
  ABS: 'АБС: выдача',
};

export const OPTION_TYPE_LABELS: Record<string, string> = {
  REQUESTED: 'Как вы просили',
  AMOUNT_REDUCED: 'Меньше сумма',
  TERM_EXTENDED: 'Дольше срок',
  PRODUCT_CHANGED: 'Кредитная линия',
};

export const STAFF_ACTION_LABELS: Record<string, string> = {
  TAKE: 'Взять в работу',
  RELEASE: 'Вернуть в очередь',
  APPROVE: 'Одобрить',
  MAKE_COUNTER_OFFER: 'Изменить условия',
  REQUEST_INFO: 'Запросить данные',
  DECLINE: 'Отказать',
  CONFIRM_DECISION: 'Подтвердить решение',
  RETURN_DECISION: 'Вернуть решение',
  RETRY_PROCESSING: 'Повторить обработку',
};

export const OUTCOME_LABELS: Record<string, string> = {
  APPROVED: 'Одобрение',
  COUNTER_OFFER: 'Контрпредложение',
  DECLINED: 'Отказ',
  NEEDS_INFO: 'Дозапрос',
  MANUAL_REVIEW: 'Ручное рассмотрение',
};

export const STOP_FACTOR_LABELS: Record<string, string> = {
  SF_COMPANY_NOT_FOUND: 'Не найден в реестре',
  SF_COMPANY_STATUS: 'Статус компании',
  SF_BUSINESS_AGE: 'Возраст бизнеса',
  SF_UNRELIABLE_REGISTRY_DATA: 'Недостоверные сведения',
  SF_CURRENT_DELINQUENCY: 'Текущая просрочка',
  SF_TAX_ARREARS: 'Налоговая недоимка',
  SF_COMPLIANCE: 'Комплаенс',
};

export const RULE_LABELS: Record<string, string> = {
  'POL-01': 'Стоп-факторы',
  'POL-02': 'Подтверждение дохода',
  'POL-03': 'Минимальный грейд',
  'POL-04': 'Расчет долговой нагрузки',
  'POL-05': 'Причины ручного рассмотрения',
  'POL-06': 'Одобрение',
  'POL-07': 'Контрпредложение',
};

export const RULE_RESULT_LABELS: Record<string, string> = {
  PASS: 'не сработало',
  FIRE: 'сработало',
  CALC: 'расчет',
};

export const DECISION_VALUE_LABELS: Record<string, string> = {
  rate_percent: 'Ставка по матрице грейда, %',
  income_source: 'Источник подтвержденного дохода',
  max_debt_load: 'Предельная долговая нагрузка',
  income_for_dti: 'Доход для расчета нагрузки, ₽/мес',
  allowed_payment: 'Допустимый платеж, ₽/мес',
  income_confirmed: 'Подтвержденный доход, ₽/мес',
  revenue_mismatch: 'Расхождение заявленной и подтвержденной выручки',
  existing_payments: 'Текущие платежи по кредитам, ₽/мес',
  requested_payment: 'Платеж по запросу, ₽/мес',
  max_amount_requested_term: 'Максимальная сумма на запрошенный срок, ₽',
};

export const TAX_REGIMES: Record<string, string> = {
  OSN: 'Общая система',
  USN_INCOME: 'Упрощенная (доходы)',
  USN_INCOME_EXPENSE: 'Упрощенная (доходы минус расходы)',
  PATENT: 'Патент',
  ESHN: 'Сельхозналог',
};

export const COMPANY_STATUSES: Record<string, string> = {
  ACTIVE: 'Действует',
  LIQUIDATING: 'В процессе ликвидации',
  BANKRUPTCY: 'Банкротство',
  REORGANIZING: 'Реорганизация',
  LIQUIDATED: 'Деятельность прекращена',
};

export const SME_CATEGORIES: Record<string, string> = {
  MICRO: 'Микропредприятие',
  SMALL: 'Малое предприятие',
  MEDIUM: 'Среднее предприятие',
};

export const APPLICANT_TYPES: Record<string, string> = {
  LEGAL_ENTITY: 'ООО (юридическое лицо)',
  INDIVIDUAL_ENTREPRENEUR: 'ИП',
};

export const ROLE_LABELS: Record<string, string> = {
  CLIENT: 'Клиент',
  UNDERWRITER: 'Андеррайтер',
  RISK_MANAGER: 'Риск-менеджер',
  SYSTEM: 'Система',
  TIMER: 'Таймер',
};

/** Draft form fields: label and the wizard step where the client fixes them. */
export type FormStep = 'company' | 'terms' | 'documents' | 'review';

export const FIELD_META: Record<string, { label: string; step: FormStep }> = {
  applicant_inn: { label: 'ИНН', step: 'company' },
  representative_role: { label: 'Кем вы являетесь в компании', step: 'company' },
  purpose: { label: 'Цель кредита', step: 'terms' },
  amount: { label: 'Сумма', step: 'terms' },
  term_months: { label: 'Срок', step: 'terms' },
  monthly_revenue_declared: { label: 'Средняя выручка в месяц', step: 'terms' },
  existing_monthly_payments_declared: { label: 'Платежи по кредитам в месяц', step: 'terms' },
  owner_guarantee_agreed: { label: 'Поручительство собственника', step: 'terms' },
  collateral_type: { label: 'Тип залога', step: 'terms' },
  collateral_description: { label: 'Описание залога', step: 'terms' },
  collateral_value: { label: 'Стоимость залога', step: 'terms' },
  collateral_owner: { label: 'Чье имущество', step: 'terms' },
  investment_project_description: { label: 'Описание проекта', step: 'terms' },
  own_contribution_amount: { label: 'Собственные средства', step: 'terms' },
  client_comment: { label: 'Комментарий для банка', step: 'terms' },
};

export function fieldMeta(field: string): { label: string; step: FormStep } {
  if (field.startsWith('consents.')) return { label: 'Согласия', step: 'review' };
  if (field.startsWith('documents')) return { label: 'Документы', step: 'documents' };
  return FIELD_META[field] ?? { label: field, step: 'review' };
}
