/*
 * Synthetic demo accounts and scenario inputs (docs/product/demo-scenarios.md). Shown only when the
 * backend reports DEMO_MODE (GET /api/v1/meta); passwords are public test values from README.
 */
export interface DemoAccount {
  login: string;
  password: string;
  role: 'CLIENT' | 'UNDERWRITER' | 'RISK_MANAGER';
  who: string;
  scenario: string;
}

export interface DemoScenario {
  code: string;
  title: string;
  inn: string;
  company: string;
  purpose: string;
  product: string;
  amount: string;
  term: string;
  revenue: string;
  payments: string;
  role: string;
  extra?: string;
  outcome: string;
}

const CLIENT_PASSWORD = 'Demo-Client-2026';

export const DEMO_ACCOUNTS: DemoAccount[] = [
  { login: 'client.irina', password: CLIENT_PASSWORD, role: 'CLIENT', who: 'Ирина, ИП, кофейня', scenario: 'S1 автоодобрение и выдача' },
  { login: 'client.marina', password: CLIENT_PASSWORD, role: 'CLIENT', who: 'Марина, финансовый директор ООО', scenario: 'S3 дозапрос и ручное рассмотрение' },
  { login: 'client.sergey', password: CLIENT_PASSWORD, role: 'CLIENT', who: 'Сергей, начинающий ИП', scenario: 'S4 отказ по стоп-факторам' },
  { login: 'client.oleg', password: CLIENT_PASSWORD, role: 'CLIENT', who: 'Олег, сотрудник компании', scenario: 'S5 сбой внешнего сервиса' },
  { login: 'client.andrey', password: CLIENT_PASSWORD, role: 'CLIENT', who: 'Андрей, директор ООО', scenario: 'S2 контрпредложение' },
  { login: 'client.demo', password: CLIENT_PASSWORD, role: 'CLIENT', who: 'Свободная проверка', scenario: '7 профилей и любой корректный ИНН' },
  { login: 'uw.dmitry', password: 'Demo-Uw-2026', role: 'UNDERWRITER', who: 'Дмитрий, андеррайтер', scenario: 'очередь, карточка, решения' },
  { login: 'uw.anna', password: 'Demo-Uw-2026', role: 'UNDERWRITER', who: 'Анна, андеррайтер', scenario: 'гонка "Взять в работу"' },
  { login: 'risk.elena', password: 'Demo-Risk-2026', role: 'RISK_MANAGER', who: 'Елена, риск-менеджер', scenario: '4 глаза, метрики, версии, аудит' },
];

export const DEMO_SCENARIOS: Record<string, DemoScenario> = {
  'client.irina': {
    code: 'S1', title: 'Автоодобрение экспресс-кредита', inn: '002000010193', company: 'ИП Примерова И.О.',
    purpose: 'Купить оборудование или транспорт', product: 'Экспресс-кредит', amount: '1 200 000', term: '24 месяца',
    revenue: '1 500 000', payments: '0', role: 'Собственник', outcome: 'Одобрение за секунды, подписание кодом, выдача',
  },
  'client.andrey': {
    code: 'S2', title: 'Контрпредложение', inn: '0010002014', company: 'ООО "Эскиз-Климат"',
    purpose: 'Закрыть кассовый разрыв', product: 'Оборотный кредит', amount: '15 000 000', term: '12 месяцев',
    revenue: '7 500 000', payments: '950 000', role: 'Генеральный директор', extra: 'Отметьте согласие на поручительство собственника',
    outcome: 'Банк предложит 3 варианта: дольше срок, меньше сумма, кредитная линия',
  },
  'client.marina': {
    code: 'S3', title: 'Дозапрос и ручное рассмотрение', inn: '0010003018', company: 'ООО "Образец-Фуд"',
    purpose: 'Купить оборудование или транспорт', product: 'Инвестиционный кредит', amount: '40 000 000', term: '60 месяцев',
    revenue: '6 750 000', payments: '600 000', role: 'Финансовый директор',
    extra: 'Залог: приобретаемое имущество, 48 000 000, принадлежит заявителю; приложите 2 документа (любой PDF, JPG или PNG)',
    outcome: 'Специалист запросит пояснения, затем одобрит; решение подтвердит риск-менеджер',
  },
  'client.sergey': {
    code: 'S4', title: 'Отказ по стоп-факторам', inn: '002000040102', company: 'ИП Пробников С.А.',
    purpose: 'Закупить товар, сырье или материалы', product: 'Экспресс-кредит', amount: '2 000 000', term: '12 месяцев',
    revenue: '600 000', payments: '0', role: 'Собственник', outcome: 'Раннее предупреждение, затем понятный отказ и дата, когда можно подать снова',
  },
  'client.oleg': {
    code: 'S5', title: 'Сбой внешнего сервиса', inn: '0010005015', company: 'ООО "Макет-Трейд"',
    purpose: 'Закупить товар, сырье или материалы', product: 'Экспресс-кредит', amount: '3 000 000', term: '24 месяца',
    revenue: '6 000 000', payments: '300 000', role: 'Сотрудник, отвечающий за финансирование', extra: 'Отметьте согласие на поручительство собственника',
    outcome: 'Бюро кредитных историй ответит не сразу: заявка подождет и получит одобрение. Перед показом сотрудник нажимает "Сбросить сбои" на демо-панели',
  },
};

export const DEMO_EXTRA_INNS: { inn: string; note: string }[] = [
  { inn: '0010006019', note: 'ликвидация: отказ по стоп-фактору' },
  { inn: '002000070107', note: 'налоговая недоимка: отказ' },
  { inn: '0010008016', note: 'крупная ООО: 12 млн одобрение, 25 млн ручное рассмотрение' },
  { inn: '002000090181', note: 'ИП без кредитной истории: одобрение' },
  { inn: '002000100136', note: 'ИП без счета: дозапрос выписки' },
  { inn: '0010011019', note: 'слабая ООО: отказ по скорингу' },
  { inn: '0010012012', note: 'комплаенс-флаг: отказ' },
  { inn: '0099000014', note: 'не найден в реестре' },
];
