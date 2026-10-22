import type { ClientApplication, OptionView } from '@/shared/api/types';

const STEPS = ['Заявка', 'Отправлена', 'Проверка данных', 'Рассмотрение специалистом', 'Решение', 'Подписание', 'Выдача', 'Готово'];

/** Contract-shaped synthetic client application (ClientApplication from docs/api/openapi.json). */
export function makeApp(overrides: Partial<ClientApplication> = {}): ClientApplication {
  return {
    id: '11111111-1111-4111-8111-111111111111',
    application_number: 'A-000101',
    version: 7,
    product_code: 'EXPRESS',
    product_name: 'Экспресс-кредит',
    purpose: 'EQUIPMENT',
    purpose_title: 'Купить оборудование или транспорт',
    form: { product_code: 'EXPRESS', purpose: 'EQUIPMENT', amount: '1200000.00', term_months: 24, applicant_inn: '002000010193', monthly_revenue_declared: '1500000.00' },
    applicant_type: 'INDIVIDUAL_ENTREPRENEUR',
    inn_check_status: 'FOUND',
    company: { company_short_name: 'ИП Тестов Т.Т.' },
    early_warnings: [],
    client_status: 'SPECIALIST_REVIEW',
    client_status_text: {
      title: 'Заявку рассматривает специалист',
      what_is_happening: 'Заявку изучает кредитный специалист банка.',
      what_next: 'Специалист примет решение или попросит уточнения здесь, в кабинете.',
      deadline_text: 'Решение до 23 октября, 18:00',
      deadline_at: null,
      notes: [],
    },
    progress_step: 4,
    progress: STEPS.map((title, i) => ({ step: i + 1, title, state: i < 3 ? 'DONE' : i === 3 ? 'CURRENT' : 'PENDING', note: null })),
    action_required: false,
    available_actions: [],
    consents: [],
    documents: [],
    required_documents: [],
    warnings: [],
    info_request: null,
    decision: null,
    offer: null,
    final_terms: null,
    signing: null,
    loan: null,
    timeline: [{ client_status: 'SENT', title: 'Заявка отправлена', at: '2026-10-23T08:00:00Z' }],
    notifications: [],
    created_at: '2026-10-23T07:55:00Z',
    updated_at: '2026-10-23T08:00:00Z',
    submitted_at: '2026-10-23T08:00:00Z',
    ...overrides,
  };
}

export function makeOption(overrides: Partial<OptionView> = {}): OptionView {
  return {
    id: '22222222-2222-4222-8222-222222222222',
    option_type: 'AMOUNT_REDUCED',
    product_code: 'WORKING_CAPITAL',
    product_name: 'Оборотный кредит',
    amount: '13950000.00',
    term_months: 12,
    rate_percent: '19.00',
    monthly_payment: '1285584.27',
    total_payment: '15427011.24',
    overpayment: '1477011.24',
    requires_owner_guarantee: true,
    requires_collateral: false,
    tranche_max_term_months: null,
    recommended: false,
    difference_text: 'на 1 050 000 ₽ меньше',
    credit_line: null,
    ...overrides,
  };
}
