# Артефакты аналитики: схемы и правила применения

Версии: скоринговая карта `scorecard-2026.10-v1`, политика `policy-2026.10-v1`, golden-файл `golden-2026.10-v1`, демо-данные `demo-2026.10-v1`, история `history-2026.10-v1`.

Все файлы генерируются командой `uv run --python 3.12 python -m src.build_all` из каталога `analytics/` (см. [../README.md](../README.md)) и не редактируются руками. Источник истины для бэкенда: `scorecard.v1.json` и `policy.v1.json`. Эталонная реализация на чистом Python (stdlib, `Decimal`): `analytics/src/oracle/` (`features.py`, `scoring.py`, `policy.py`, `money.py`, `inn.py`).

| Файл | Кто читает | Назначение |
|---|---|---|
| `scorecard.v1.json` | api (воркер, задача `SCORE`) | балльная карта: признаки, бины, баллы, грейды, PD |
| `policy.v1.json` | api (воркер, задача `DECIDE`; API подбора и валидации) | продукты, стоп-факторы, лимиты, ставки, контрпредложения, справочник кодов причин |
| `expected_outcomes.json` | тест бэкенда (один параметризованный golden-тест), тест мока | вход и ожидаемый результат скоринга и политики для 63 случаев |
| `demo_companies.json` | integrations-mock, seed | 12 синтетических компаний и ИП с ответами всех источников и поведением мока |
| `demo_users.json` | seed api | тестовые учетные записи (пароли только для демо) |
| `synthetic_applications.json` | seed api (необязательно) | 420 исторических заявок и 11 648 событий для экрана метрик |
| `build_report.json` | документация | метрики модели, калибровка политики, метрики истории (числа для отчетов) |

## 1. Общие форматы

| Тип | Формат в JSON | Как читать в бэкенде |
|---|---|---|
| Деньги | строка с двумя знаками: `"1500000.00"` (рубли.копейки) | `Decimal(value)`, хранить `NUMERIC(18,2)` |
| Доля | строка: `"0.30"` = 30% | `Decimal(value)` |
| Ставка | строка, проценты годовых с двумя знаками: `"22.50"` = 22,5% годовых | `Decimal(value)` |
| Дата | `YYYY-MM-DD` | `date.fromisoformat` |
| Время | `YYYY-MM-DDTHH:MM:SSZ` (UTC) | `datetime` с таймзоной UTC |

Правила точности (одинаковы в оракуле и бэкенде): контекст `Decimal` с `prec = 28` (значение Python по умолчанию), без `float`; деньги округляются `ROUND_HALF_UP` до 0.01; доли и коэффициенты признаков `ROUND_HALF_UP` до 0.0001; суммы вариантов предложения округляются вниз до `counter_offer.amount_rounding` (10 000 руб.).

## 2. Формат случая (вход скоринга и политики)

Тот же формат используется в `expected_outcomes.json` (`cases[].input`) и описывает данные, которые воркер собирает к этапу `SCORING`.

```json
{
  "as_of_date": "2026-10-23",
  "application": {
    "product_code": "EXPRESS", "purpose": "INVENTORY", "amount": "3000000.00", "term_months": 24,
    "applicant_type": "LEGAL_ENTITY", "applicant_inn": "0010005015",
    "monthly_revenue_declared": "6000000.00", "existing_monthly_payments_declared": "300000.00",
    "collateral_value": null, "collateral_type": null
  },
  "state": {"auto_info_request_count": 0, "manual_review_required": false, "bank_statement_attached": false},
  "sources": {"REGISTRY": {}, "FNS": {}, "FINANCIAL_STATEMENTS": {}, "CREDIT_BUREAU": {}, "BANK_TURNOVER": {}}
}
```

- `as_of_date`: дата расчета (дата выполнения задачи `SCORE` по Москве). От нее считается возраст бизнеса.
- `state.auto_info_request_count`, `state.manual_review_required`: поля заявки из стейт-машины.
- `state.bank_statement_attached`: клиент приложил документ `BANK_STATEMENT` (в ответ на дозапрос `NI_INCOME_NOT_CONFIRMED`).
- `sources.*`: тела ответов моков (раздел 6). `FINANCIAL_STATEMENTS = null` для ИП (источник не вызывается).

## 3. `scorecard.v1.json`

| Поле | Тип | Смысл |
|---|---|---|
| `schema`, `schema_version` | строка, число | `"scorecard"`, `1`; меняется при несовместимом изменении формата |
| `version` | строка | версия карты, пишется в `scoring_result.scorecard_version` и в решение |
| `created_at`, `author`, `description` | строки | происхождение |
| `scaling` | объект | справочно: `base_score` 600 при шансах `base_odds_good_to_bad` 50:1, `pdo` 20, `factor` = PDO / ln 2, `offset`, `intercept` логистической регрессии. Для расчета балла не нужен |
| `bin_rule` | строка | правило попадания в бин (ниже) |
| `feature_parameters` | объект | параметры вычисления признаков: `min_turnover_months` (6), `min_turnover_months_for_growth` (12), `okved_risk_groups` (класс ОКВЭД из двух цифр → `LOW`/`MEDIUM`/`HIGH`), `okved_default_group` (`MEDIUM`), `mass_registration_flags` |
| `base_points` | целое | базовый балл, к которому прибавляются баллы факторов |
| `factors[]` | массив | факторы карты (11 штук), порядок совпадает с порядком в `factor_contributions` |
| `factors[].code` | строка | код признака (раздел 3.1) |
| `factors[].name` | строка | название для сотрудника |
| `factors[].sources` | массив | источники данных |
| `factors[].type` | `numeric` / `categorical` | тип |
| `factors[].definition` | строка | как вычисляется признак (совпадает с `features.py`) |
| `factors[].coefficient`, `factors[].iv` | числа | справочно: коэффициент регрессии и Information Value |
| `factors[].bins[]` | массив | бины: `id`, `label` (для карточки сотрудника), `points` (целое); для `numeric`: `lower`, `upper` (строки-числа или `null`); для `categorical`: `values[]`. Поля `woe`, `train_count`, `train_bad_rate` справочные |
| `factors[].missing` | объект | бин "нет данных": `id`, `label`, `points`; `points_before_cap` справочно (раздел 3.2) |
| `grade_bands[]` | массив | `{grade, min_score}` от A к E; первый бин, для которого `score >= min_score`, дает грейд; у E `min_score = null` |
| `pd_by_grade` | объект | ожидаемая вероятность дефолта на 12 мес. по грейду (строки-доли) |
| `monitoring` | объект | `grade_distribution_dev`: доли грейдов в выборке разработки (эталон для PSI на экране метрик), `psi_thresholds` |

**Правило бинов.** Числовой бин: `lower <= x < upper`, `null` означает отсутствие границы; бины покрывают всю ось без пропусков. Категориальный бин: `x` входит в `values`. Значение `null` (нет данных) или категория, которой нет ни в одном бине, попадает в `missing`.

**Расчет.** `score = base_points + сумма points выбранных бинов всех factors`; `grade` по `grade_bands`; `pd = pd_by_grade[grade]`. Выход для карточки: `factor_contributions[] = {factor_code, factor_name, value, bin_id, bin_label, points}`.

### 3.1. Признаки

Определения дословно в `factors[].definition` и в `analytics/src/oracle/features.py`. Сводка:

| Код | Вычисление |
|---|---|
| `business_age_months` | полных месяцев от `REGISTRY.registration_date` до `as_of_date` (если день месяца `as_of` меньше дня регистрации, месяц не засчитывается) |
| `industry_risk_group` | `feature_parameters.okved_risk_groups[okved_main_code[:2]]`, иначе `okved_default_group` |
| `confirmed_monthly_revenue` | `BANK_TURNOVER.avg_monthly_inflow_12m` при `has_account` и `months_available >= 6`, иначе `FINANCIAL_STATEMENTS.revenue / 12` (до копеек), иначе нет данных |
| `revenue_growth` | при 12 месяцах оборотов: (сумма 6 последних мес. - сумма 6 предыдущих) / сумма 6 предыдущих; иначе (revenue - revenue_prev_year) / revenue_prev_year; иначе нет данных |
| `debt_load_ratio` | `max(анкета.existing_monthly_payments_declared, БКИ.monthly_payments_total) / min(анкета.monthly_revenue_declared, confirmed_monthly_revenue)`; если подтвержденной выручки нет, знаменатель = заявленная выручка |
| `bki_max_delinquency_days_12m`, `bki_inquiries_90d`, `bki_credit_history_months` | поля БКИ; нет данных при `no_record = true` |
| `tax_arrears_flag` | `YES`, если `FNS.tax_arrears_amount > 0` |
| `turnover_volatility` | коэффициент вариации доступных месяцев оборотов (стандартное отклонение с делением на n / среднее), при `months_available >= 6` |
| `net_margin` | `net_profit / revenue` из ГИР БО (только ООО) |

### 3.2. Экспертная корректировка

Баллы бина "нет данных" ограничены сверху нулем: отсутствие данных не может улучшать балл (например, отсутствие кредитной истории не дает бонуса). Исходные значения сохранены в `points_before_cap`.

## 4. `policy.v1.json`

| Поле | Смысл |
|---|---|
| `schema`, `schema_version`, `version`, `effective_from`, `author`, `description`, `formats` | версия и форматы |
| `products.<CODE>` | параметры продуктов `EXPRESS`, `WORKING_CAPITAL`, `CREDIT_LINE`, `INVESTMENT`: `name`, `direct_application`, `applicant_types`, `allowed_purposes`, `amount_min`, `amount_max`, `amount_step`, `term_min_months`, `term_max_months`, `base_rate_percent`, `review_mode` (`AUTO`, `AUTO_WITH_MANUAL`, `MANUAL`), `auto_approval_limit`, `green_grades`, `gray_grades`, `decline_grades`, `min_business_age_months`, `requires_owner_guarantee_for`, `requires_collateral`, `min_collateral_coverage`, `required_documents`, `tranche_max_term_months` (только линия) |
| `stop_factors.blocked_company_statuses` | `LIQUIDATING`, `BANKRUPTCY`, `REORGANIZING`, `CEASED` |
| `stop_factors.unreliable_flags` | признаки ФНС, дающие отказ: `UNRELIABLE_ADDRESS`, `UNRELIABLE_DIRECTOR`, `MASS_ADDRESS`, `MASS_DIRECTOR`, `DISQUALIFIED_DIRECTOR` |
| `stop_factors.current_delinquency_min_days` | 30: текущая просрочка в БКИ не меньше порога дает отказ |
| `stop_factors.tax_arrears_stop_amount` | `"100000.00"`: недоимка не меньше порога дает отказ, от 0,01 до порога дает ручное рассмотрение |
| `stop_factors.compliance_stop_flags` | `["RED"]`: значения `BANK_TURNOVER.compliance_flag` для `SF_COMPLIANCE` |
| `income.income_source_priority` | `BANK_TURNOVER`, `FINANCIAL_STATEMENTS`, `BANK_STATEMENT` |
| `income.min_turnover_months` | 6: минимум месяцев оборотов, чтобы считать их подтверждением |
| `income.revenue_mismatch_threshold` | `"0.30"` |
| `max_debt_load_by_grade` | A `0.30`, B `0.25`, C `0.20`, D `0.15`, E `0.10`: максимальная доля всех платежей в месячной выручке |
| `rate_premium_by_grade` | A `0.00`, B `0.50`, C `2.00`, D `5.50`, E `13.50`: надбавка к базовой ставке, п.п. |
| `counter_offer` | `counter_offer_min_share` 0.30, `max_counter_options` 3, `amount_rounding` 10 000, `option_order`, `recommended_priority`, `credit_line_product`, `credit_line_source_products`, `credit_line_suggest_purposes` |
| `authority` | `underwriter_authority_limit` 50 000 000, `override_requires_risk_approval` |
| `process` | `max_auto_info_cycles` 3, `offer_ttl_days` 7, `info_response_ttl_days` 14, `draft_ttl_days` 30, `manual_review_sla_hours` 8, `decision_sla_auto_minutes` 15, `decision_sla_manual_hours` 24 (последние два для North Star) |
| `info_request_templates` | пункты дозапроса, которые создает политика (`NI_INCOME_NOT_CONFIRMED`: документ `BANK_STATEMENT` и поле `monthly_revenue_declared`) |
| `rules[]` | POL-01...POL-07: `id`, `name`, `terminal`, `outcome`, `reason_codes` (какие коды выдает правило), `parameters` (какие параметры использует) |
| `reason_codes.<CODE>` | справочник: `rule`, `outcome`, `client_visibility` (`FULL`, `GENERIC`, `NONE`), `client_text`, `client_next_step`, `employee_text`; подстановки в фигурных скобках берутся из `reason_details` решения |

### 4.1. Алгоритм политики

Порядок и тексты из [docs/process/decision-model.md](../../docs/process/decision-model.md). Уточнения, которые нужны для точного совпадения с оракулом:

1. **POL-01.** Если `REGISTRY.found = false`: только `SF_COMPANY_NOT_FOUND`. Иначе проверяются все стоп-факторы, коды в порядке: `SF_COMPANY_STATUS`, `SF_BUSINESS_AGE`, `SF_UNRELIABLE_REGISTRY_DATA` (пересечение `FNS.unreliable_flags` и `stop_factors.unreliable_flags`), `SF_CURRENT_DELINQUENCY` (только при `no_record = false`), `SF_TAX_ARREARS`, `SF_COMPLIANCE`. Любой сработавший: `DECLINED`.
2. **POL-02.** Доход: обороты (если `has_account` и `months_available >= income.min_turnover_months` и среднее больше 0), иначе ГИР БО `revenue / 12`, иначе заявленная выручка с источником `BANK_STATEMENT`, если `state.bank_statement_attached`. Если дохода нет: `NEEDS_INFO` с `NI_INCOME_NOT_CONFIRMED` при `auto_info_request_count < max_auto_info_cycles`, иначе `MANUAL_REVIEW` с `MR_INFO_CYCLES_EXCEEDED`.
3. **POL-03.** Грейд в `decline_grades` продукта: `DECLINED`, `DCL_LOW_SCORE`.
4. **POL-04.** `revenue_mismatch = ratio(заявленная - подтвержденная, подтвержденная)` (не считается для `BANK_STATEMENT`); `income_for_dti = min(заявленная, подтвержденная)`; `existing_payments = max(анкета, БКИ)`; `allowed_payment = money(max(income_for_dti x max_debt_load_by_grade[grade] - existing_payments, 0))`; `rate = base_rate_percent + rate_premium_by_grade[grade]`; `requested_payment = annuity(amount, rate, term)`; `max_amount(n) = floor_10000(min(allowed_payment x (1 - (1+i)^-n) / i, amount_max))`, `i = rate / 1200`.
5. **POL-05.** Причины собираются в порядке справочника: `MR_PRODUCT_MANUAL_ONLY` (режим `MANUAL`); `MR_AMOUNT_ABOVE_AUTO_LIMIT` (`amount > auto_approval_limit`, только если режим не `MANUAL`, иначе причина дублировала бы первую); `MR_GRAY_ZONE`; `MR_DATA_MISMATCH` (`revenue_mismatch > threshold`, строго больше); `MR_TAX_ARREARS_MINOR` (`0 < недоимка < tax_arrears_stop_amount`); `MR_INCOME_DOCUMENT_CHECK`; `MR_COLLATERAL_REVIEW` (`ratio(collateral_value, amount) < min_collateral_coverage`); `MR_RETURNED_AFTER_INFO` (`state.manual_review_required`). Есть хотя бы одна: `MANUAL_REVIEW` и `recommendation` = результат шагов 6-7 в режиме рекомендации.
6. **POL-06.** `requested_payment <= allowed_payment`: `APPROVED`, вариант `REQUESTED` (`recommended = true`). Если цель в `credit_line_suggest_purposes` и линия допустима (шаг 7, вариант линии), добавляется вариант `PRODUCT_CHANGED` и код `CO_PRODUCT_ALTERNATIVE`.
7. **POL-07.** Иначе варианты в порядке `AMOUNT_REDUCED`, `TERM_EXTENDED`, `PRODUCT_CHANGED`:
   - `AMOUNT_REDUCED`: сумма `max_amount(term)`; включается, если `>= amount_min`, `>= amount x counter_offer_min_share`, `< amount` и (только в авторежиме) `<= auto_approval_limit`.
   - `TERM_EXTENDED`: минимальный `n` от `term + 1` до `term_max_months`, при котором `annuity(amount, rate, n) <= allowed_payment`.
   - `PRODUCT_CHANGED` (кредитная линия): исходный продукт в `credit_line_source_products`; цель в `allowed_purposes` линии; возраст бизнеса не меньше минимума линии; грейд не в `gray_grades` и не в `decline_grades` линии. Лимит `L = min(max_amount_line(tranche_max_term_months) по ставке линии, amount_max линии, запрошенная сумма, auto_approval_limit линии (только в авторежиме))`; включается при `L >= amount_min` линии. Срок договора варианта = запрошенный срок, приведенный к `term_min_months...term_max_months` линии; `monthly_payment`, `total_payment`, `overpayment` линии считаются как аннуитет лимита на `tranche_max_term_months` (12 мес.), это "платеж, если взять весь лимит на 12 месяцев" из каталога.
   - `recommended = true` получает первый найденный тип из `recommended_priority` (`TERM_EXTENDED`, `AMOUNT_REDUCED`, `PRODUCT_CHANGED`). Нет вариантов: `DECLINED`, `DCL_AFFORDABILITY`. Есть: `COUNTER_OFFER`, коды `CO_DEBT_LOAD` и при наличии линии `CO_PRODUCT_ALTERNATIVE`.
8. **Режим рекомендации** (внутри `MANUAL_REVIEW`): шаги 6-7 без ограничения `auto_approval_limit`.

Поля варианта: `option_type`, `product_code`, `amount`, `term_months`, `rate_percent`, `monthly_payment`, `total_payment`, `overpayment`, `requires_owner_guarantee` (тип заявителя в `requires_owner_guarantee_for`), `requires_collateral`, `tranche_max_term_months`, `recommended`.

Выход политики (как в golden-файле): `outcome`, `mode` (`AUTO`), `reason_codes`, `reason_details` (значения для подстановки в тексты), `rules_path` (`[{rule, result}]`, где `result` = `PASS`, `FIRE` или `CALC`), `values` (промежуточные значения POL-04, `null` если до POL-04 не дошли), `options`, `recommendation`, `info_request_items`, `policy_version`.

## 5. `expected_outcomes.json` и golden-тест

| Поле | Смысл |
|---|---|
| `scorecard_version`, `policy_version`, `scorecard_sha256`, `policy_sha256` | на каких конфигах получены ожидания; тест сначала проверяет, что загружены те же версии |
| `compare` | что сравнивать |
| `mock_profiles[]` | 6 профилей детерминированного генератора на дату `2026-10-23`: мок проверяет, что `generate_profile(inn, as_of)` дает те же ответы |
| `cases[]` | 63 случая: `demo` (15 запросов по 12 демо-компаниям), `boundary` (30 граничных: пороги стоп-факторов, равенство платежа допустимому, лимит авто-полномочий, расхождение ровно 30%, покрытие залогом, циклы дозапросов и т.д.), `population` (12 синтетических заявок на границах грейдов и путях серой зоны), `mockgen` (6 профилей генератора) |
| `cases[].input` | случай в формате раздела 2 |
| `cases[].expected` | `features`, `score`, `grade`, `pd`, `factor_contributions`, `decision` |

Как проверить совпадение: один параметризованный тест по `cases[]`: построить из `input` тот же объект, что получает воркер, вызвать скоринг и политику бэкенда и сравнить `score`, `grade`, `pd`, баллы `factor_contributions`, значения признаков факторов карты, а также `decision.outcome`, `reason_codes`, `rules_path`, `values`, `options` и `recommendation` (деньги как `Decimal`). Расхождение в любом поле означает, что реализация отличается от спецификации.

## 6. `demo_companies.json` и мок

Структура компании: `profile_id` (`S1`...`S5`, `X1`...`X7`), `scenario`, `title`, `inn`, `applicant_type`, `client_login`, `registration_months_ago`, `note`, `mock_behavior`, `sources` (тела ответов пяти источников), `demo_requests[]` (параметры анкеты для сценария и `expected`: балл, грейд, исход, коды, варианты).

Правила для `services/integrations-mock`:

1. Ответы источников отдаются из `sources`. Поле `REGISTRY.registration_date` пересчитывается при каждом запросе: текущая дата минус `registration_months_ago` месяцев (тот же день месяца, при его отсутствии последний день месяца), чтобы возраст бизнеса в демо не менялся со временем. `inflow_by_month` содержит 12 последних полных месяцев от старого к новому, `null` означает месяц без данных; мок может добавить подписи месяцев.
2. `FINANCIAL_STATEMENTS = null` у ИП: источник для ИП не вызывается (при вызове мок отвечает 404). `{"found": false}` у ООО: отчетности нет. `CREDIT_BUREAU = {"no_record": true}`: кредитной истории нет.
3. `mock_behavior.<SOURCE> = {"fail_first_n": N, "failure": "TIMEOUT" | "HTTP_500"}`: первые N запросов к источнику по этому ИНН завершаются сбоем (таймаут: ответ не раньше чем через 6 сек при таймауте клиента 5 сек; или HTTP 500), дальше обычный ответ. Счетчик в памяти мока, сбрасывается служебным endpoint (например `POST /admin/reset`). Для S5: БКИ, `fail_first_n = 4`.
4. Задержка ответа по умолчанию 200-800 мс (детерминированно от ИНН или случайно, на результат не влияет).
5. ИНН, которого нет в файле: при неверной контрольной сумме 400; иначе профиль строится функцией `generate_profile(inn, as_of)` из `analytics/src/mockgen.py` (только stdlib, можно скопировать в мок как есть). Правило "не найден": цифры 3-4 ИНН равны `99` (пример `0099000014`).

Алгоритм генератора: `seed = int(sha256("profile:" + inn).hexdigest()[:16], 16)`, генератор `random.Random(seed)`, используется только `random()`; нормальное распределение приближается суммой 12 равномерных, `exp` и `log` считаются рядами без `math.exp`/`math.log`, поэтому результат побитно одинаков на любой платформе. Тип заявителя по длине ИНН, латентное качество заемщика определяет возраст, выручку, волатильность, нагрузку, просрочки и признаки ФНС (подробно в [docs/analytics/synthetic-data.md](../../docs/analytics/synthetic-data.md)).

## 7. `demo_users.json`

`users[]`: `login`, `password` (демо, публичный), `role` (`CLIENT`, `UNDERWRITER`, `RISK_MANAGER`), `full_name` (вымышленное), `representative_role` (для клиента), `persona`, `scenarios`, `company_inns` (компании, от имени которых клиент подает заявки), `is_demo = true`. В БД хранится только хеш пароля.

## 8. `synthetic_applications.json`

`reference_now` (`2026-10-22T21:00:00Z`, то есть 2026-10-23 00:00 МСК), `window_days` 90, `applications[]` (одна строка на заявку: поля `application`, итоговые условия, `status`, `version`, `score`, `grade`, `decisions[]`, `offers[]`, `assignee`, счетчики дозапросов, `sla_breached`), `events[]` (формат [events.md](../../docs/process/events.md): `event_id`, `event_type`, `occurred_at`, `application_id`, `actor_type`, `actor_login`, `correlation_id`, `application_version`, `payload`). Вместо `actor_id` указан `actor_login`: загрузчик сопоставляет логин с id пользователя; логины `hist.client.NNN` создаются как неактивные клиенты без пароля. При загрузке все отметки времени сдвигаются на `now - reference_now`, чтобы история заканчивалась текущим моментом. В `payload` нет персональных данных.

## 9. Версионирование

Любое изменение чисел карты или политики делается в `analytics/src` и пересборкой; версия в `config_base.py` увеличивается (`scorecard-2026.10-v2`, `policy-2026.10-v2`), golden-файл пересобирается вместе с конфигами. Бэкенд хранит версии в каждом решении и пишет событие `CONFIG_VERSION_LOADED` с `sha256` файла.
