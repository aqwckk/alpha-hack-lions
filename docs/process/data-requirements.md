# Требования к данным заявки

Статус: **принято для реализации MVP**. Документ задает словарь данных, правила валидации, обязательность по продуктам, внешние данные, документы, согласия и классификацию по чувствительности. Имена полей (snake_case) рекомендуются для API и БД; если бэкенд меняет имя, он отражает это в OpenAPI и модели данных, а смысл и правила остаются отсюда.

Принцип из исследования (H2, ПР-2): **клиент вводит только то, чего банк не может узнать сам** (цель, сумма, срок, выручка, текущие платежи, сведения о залоге). Остальное подставляется по ИНН.

## 1. Поля, которые вводит клиент

Обозначения обязательности: **О** обязательно, **У** условно (условие в столбце валидации), **Н** необязательно, **-** не применяется. Продукты: E `EXPRESS`, W `WORKING_CAPITAL`, I `INVESTMENT`. Для `CREDIT_LINE` прямая заявка не создается.

| Поле | Название для клиента | Тип | E | W | I | Валидация | Класс |
|---|---|---|---|---|---|---|---|
| `product_code` | Продукт | enum: `EXPRESS`, `WORKING_CAPITAL`, `INVESTMENT` | О | О | О | `direct_application = true` | INTERNAL |
| `purpose` | Задача, на которую нужны деньги | enum целей ([../product/product-catalog.md](../product/product-catalog.md), раздел 1) | О | О | О | входит в `allowed_purposes` продукта | CONFIDENTIAL |
| `amount` | Сумма кредита, руб. | Decimal(18,2), целые рубли | О | О | О | в диапазоне `amount_min`...`amount_max` продукта, кратно `amount_step` (10 000) | CONFIDENTIAL |
| `term_months` | Срок, месяцев | int | О | О | О | в диапазоне `term_min_months`...`term_max_months` продукта | CONFIDENTIAL |
| `applicant_inn` | ИНН компании или ИП | string | О | О | О | только цифры; 10 цифр (ООО) или 12 цифр (ИП); контрольная сумма (раздел 2); автозаполнение не вернуло "не найден" | 10 цифр: CONFIDENTIAL; 12 цифр: RESTRICTED (ИНН физлица) |
| `representative_role` | Кем вы являетесь в компании | enum: `OWNER`, `CEO`, `CFO`, `ACCOUNTANT`, `FINANCE_MANAGER`, `OTHER_AUTHORIZED` | О | О | О | значение из списка | CONFIDENTIAL |
| `monthly_revenue_declared` | Средняя выручка в месяц за последние 12 месяцев, руб. | Decimal(18,2) | О | О | О | больше 0 и не больше 10 000 000 000 | CONFIDENTIAL |
| `existing_monthly_payments_declared` | Сколько бизнес сейчас платит по кредитам и займам в месяц, руб. | Decimal(18,2) | О | О | О | от 0 до 10 000 000 000; если больше выручки, предупреждение "Проверьте сумму: платежи больше выручки" (не блокирует) | CONFIDENTIAL |
| `owner_guarantee_agreed` | Согласен, что собственник станет поручителем | bool | У | У | У | обязательно `true`, если заявитель ООО и `requires_owner_guarantee_for` включает `LEGAL_ENTITY` | CONFIDENTIAL |
| `collateral_type` | Что предлагаете в залог | enum: `EQUIPMENT`, `VEHICLE`, `REAL_ESTATE`, `PURCHASED_ASSET` | - | - | О | значение из списка | CONFIDENTIAL |
| `collateral_description` | Описание залога | string | - | - | О | 10-500 символов | CONFIDENTIAL |
| `collateral_value` | Примерная стоимость залога, руб. | Decimal(18,2) | - | - | О | больше 0 и не больше 10 000 000 000 | CONFIDENTIAL |
| `collateral_owner` | Чье это имущество | enum: `APPLICANT`, `THIRD_PARTY` | - | - | О | значение из списка | CONFIDENTIAL |
| `investment_project_description` | Коротко о проекте: что покупаете и как это окупится | string | - | - | О | 20-2000 символов | CONFIDENTIAL |
| `own_contribution_amount` | Сколько вкладываете своих денег, руб. | Decimal(18,2) | - | - | Н | от 0 до 10 000 000 000 | CONFIDENTIAL |
| `client_comment` | Что еще важно знать банку | string | Н | Н | Н | до 1000 символов | CONFIDENTIAL |

ФИО представителя (`representative_full_name`) берется из профиля пользователя (тестовые учетные записи), в анкете не вводится. Класс RESTRICTED.

Все текстовые поля: обрезка пробелов по краям, запрет управляющих символов, вывод на страницу только с экранированием.

### 1.1. Когда проверяются поля

| Момент | Что проверяется | Результат ошибки |
|---|---|---|
| Автосохранение (`UPDATE_DRAFT`) | только формат и тип каждого переданного поля | `422` с ошибкой по полю, остальные поля сохраняются |
| Отправка (`SUBMIT`) | обязательность по продукту, диапазоны, кратность, допустимость цели, контрольная сумма ИНН, согласия, дубликат активной заявки | `422 VALIDATION_FAILED` со списком `{field, code, message}` или `409 DUPLICATE_ACTIVE_APPLICATION`; заявка остается в `DRAFT` |
| Проверка полноты (`SUBMITTED`) | документы продукта, согласованность значений | дозапрос `NI_MISSING_DOCUMENTS` |
| Ответ на дозапрос (`RESPOND_INFO`) | только запрошенные пункты, правила как при отправке | `422` по пункту |

### 1.2. Коды ошибок валидации и тексты для клиента

| Код | Текст для клиента |
|---|---|
| `REQUIRED` | Заполните это поле |
| `INVALID_FORMAT` | Проверьте формат: {hint} |
| `INN_LENGTH` | ИНН компании состоит из 10 цифр, ИНН ИП из 12 цифр |
| `INN_CHECKSUM` | В ИНН ошибка: проверьте цифры |
| `INN_NOT_FOUND` | Компания или ИП с таким ИНН не найдены в госреестре. Проверьте ИНН |
| `OUT_OF_RANGE` | Для этого продукта допустимо от {min} до {max} |
| `NOT_MULTIPLE_OF_STEP` | Сумма должна быть кратна {step} руб. |
| `PURPOSE_NOT_ALLOWED` | Этот продукт не подходит для выбранной задачи. Вернитесь к подбору |
| `CONSENT_REQUIRED` | Без этого согласия банк не сможет рассмотреть заявку |
| `GUARANTEE_REQUIRED` | Для компаний этот кредит выдается с поручительством собственника |
| `DOCUMENT_TYPE_NOT_ALLOWED` | Можно загрузить PDF, JPG или PNG |
| `DOCUMENT_TOO_LARGE` | Файл больше 10 МБ. Сожмите его или разделите на части |
| `DUPLICATE_ACTIVE_APPLICATION` | У вас уже есть заявка на этот продукт по этой компании. Продолжите ее или отмените |

## 2. Контрольная сумма ИНН

Реализуется одинаково на фронтенде (мгновенная подсказка) и на бэкенде (источник истины).

- **10 цифр (организация).** Веса для цифр 1-9: 2, 4, 10, 3, 5, 9, 4, 6, 8. Контрольное число = (сумма произведений mod 11) mod 10; должно совпасть с 10-й цифрой.
- **12 цифр (ИП, физлицо).** Первое контрольное число: веса для цифр 1-10: 7, 2, 4, 10, 3, 5, 9, 4, 6, 8; результат (сумма mod 11) mod 10 должен совпасть с 11-й цифрой. Второе: веса для цифр 1-11: 3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8; результат должен совпасть с 12-й цифрой.
- Синтетические ИНН генерирует аналитик с корректной контрольной суммой. Рекомендация: первые две цифры (код региона) `00`, такой код не присваивается реальным налогоплательщикам, поэтому синтетика не совпадет с реальной компанией.

## 3. Что подставляется автоматически по ИНН

При вводе ИНН в черновике выполняется команда `PREFILL_BY_INN` (синхронно, моки ЕГРЮЛ/ЕГРИП и ФНС, таймаут 5 сек). Подставленные поля клиент видит в блоке "Сведения из госреестров" только для чтения, с подписью источника и даты. Если мок недоступен, клиент видит "Не удалось получить сведения, попробуем при обработке заявки" и может продолжить: при отправке эти данные будут получены на этапе `ENRICHMENT`.

| Поле | Название | Источник | Класс |
|---|---|---|---|
| `applicant_type` | Тип: ООО или ИП | длина ИНН, подтверждается реестром: `LEGAL_ENTITY`, `INDIVIDUAL_ENTREPRENEUR` | INTERNAL |
| `company_full_name`, `company_short_name` | Наименование (для ИП: "ИП Фамилия И.О.") | `REGISTRY` | CONFIDENTIAL (для ИП RESTRICTED) |
| `ogrn` | ОГРН (13 цифр) или ОГРНИП (15 цифр) | `REGISTRY` | CONFIDENTIAL |
| `registration_date` | Дата регистрации, из нее возраст бизнеса в месяцах | `REGISTRY` | CONFIDENTIAL |
| `company_status` | Статус: `ACTIVE`, `LIQUIDATING`, `BANKRUPTCY`, `REORGANIZING`, `CEASED` | `REGISTRY` | CONFIDENTIAL |
| `okved_main_code`, `okved_main_name` | Основной вид деятельности | `REGISTRY` | CONFIDENTIAL |
| `legal_address_region` | Регион регистрации (полный адрес в MVP не используется) | `REGISTRY` | CONFIDENTIAL |
| `director_full_name` | Руководитель (ООО) или ФИО предпринимателя (ИП) | `REGISTRY` | RESTRICTED |
| `founders[]` | Учредители ООО: ФИО или наименование, доля в процентах | `REGISTRY` | RESTRICTED |
| `guarantor_full_name` | Поручитель: учредитель с наибольшей долей (для ООО) | вычисляется из `founders[]` | RESTRICTED |
| `sme_category` | Категория МСП: `MICRO`, `SMALL`, `MEDIUM` | `FNS` | CONFIDENTIAL |
| `tax_regime` | Режим налогообложения: `OSN`, `USN_INCOME`, `USN_INCOME_EXPENSE`, `PATENT`, `ESHN` | `FNS` | CONFIDENTIAL |
| `employees_count` | Среднесписочная численность | `FNS` | CONFIDENTIAL |

Предварительная проверка (H3, Should): по ответу реестра и ФНС сразу проверяются стоп-факторы, не требующие согласия на БКИ: статус, возраст бизнеса для выбранного продукта, признаки недостоверности. При срабатывании клиент видит предупреждение (тексты стоп-факторов из [decision-model.md](decision-model.md), раздел 9.1, с приставкой "Скорее всего, банк откажет: ..."), но может отправить заявку; окончательное решение принимает политика.

## 4. Данные внешних источников (этап `ENRICHMENT`)

Источники вызываются моками из `services/integrations-mock`. Ответы детерминированы по ИНН (профили задает аналитик). Каждый ответ сохраняется снимком (`source_snapshot`: источник, ИНН, время запроса, время ответа, длительность, номер попытки, тело ответа) и связывается с заявкой.

| Код источника | Реальный аналог | Когда вызывается | Ключевые поля ответа | Для чего | Класс |
|---|---|---|---|---|---|
| `REGISTRY` | ЕГРЮЛ (ООО) / ЕГРИП (ИП) | всегда | поля раздела 3 из реестра; `found` (bool) | стоп-факторы, возраст бизнеса, отрасль, автозаполнение | CONFIDENTIAL / RESTRICTED (ФИО) |
| `FNS` | ФНС "Прозрачный бизнес" | всегда | `sme_category`, `tax_regime`, `employees_count`, `tax_arrears_amount`, `taxes_paid_last_year`, `unreliable_flags[]` (`UNRELIABLE_ADDRESS`, `UNRELIABLE_DIRECTOR`, `MASS_ADDRESS`, `MASS_DIRECTOR`, `DISQUALIFIED_DIRECTOR`) | стоп-факторы, факторы скоринга | CONFIDENTIAL |
| `FINANCIAL_STATEMENTS` | ГИР БО | только ООО | `report_year`, `revenue`, `revenue_prev_year`, `net_profit`, `total_assets`, `equity` | подтвержденный доход, расхождение с анкетой, факторы скоринга | CONFIDENTIAL |
| `CREDIT_BUREAU` | БКИ | только при действующем согласии `CONSENT_CREDIT_BUREAU` | `no_record` (нет кредитной истории), `active_loans_count`, `total_debt`, `monthly_payments_total`, `current_delinquency_days`, `current_delinquency_amount`, `max_delinquency_days_24m`, `delinquencies_30plus_24m`, `inquiries_90d`, `credit_history_months` | стоп-фактор просрочки, текущие платежи, факторы скоринга | RESTRICTED (кредитная история) |
| `BANK_TURNOVER` | внутренние данные банка | всегда | `has_account` (bool), `months_available`, `inflow_by_month[]` (12 значений), `avg_monthly_inflow_12m`, `compliance_flag` (`NONE`, `RED`; синтетический признак внутренних проверок) | подтвержденный доход, факторы скоринга, стоп-фактор `SF_COMPLIANCE` | CONFIDENTIAL (банковская тайна) |

Мок каждого источника поддерживает настраиваемые задержку и ошибки (по ИНН или по глобальному переключателю) для сценария S5: таймаут, ответ 5xx, ошибка на первые N запросов.

## 5. Документы

Сущность `document`: `id`, `application_id`, `document_type` (справочник в [../product/product-catalog.md](../product/product-catalog.md), раздел 2.2), `file_name`, `mime_type` (`application/pdf`, `image/jpeg`, `image/png`), `size_bytes` (до 10 МБ), `sha256`, `uploaded_by`, `uploaded_at`, `info_request_item_id` (если загружен в ответ на дозапрос), `storage_key`. Класс RESTRICTED (документы могут содержать ПДн).

Правила: проверка типа по сигнатуре файла, а не только по расширению; не больше 20 файлов на заявку; удаление возможно только в `DRAFT`; после отправки документы неизменяемы. Сотрудник банка может скачать документ, факт скачивания пишется в журнал (`DOCUMENT_DOWNLOADED`).

Документы, которые формирует банк (мок ЭДО) при подготовке к подписанию: `CREDIT_AGREEMENT` (кредитный договор или договор кредитной линии), `PAYMENT_SCHEDULE` (график платежей), `GUARANTEE_AGREEMENT` (договор поручительства, для ООО), `PLEDGE_AGREEMENT` (договор залога, для `INVESTMENT`). Для каждого хранится `sha256`, по которому привязывается подпись.

## 6. Согласия

Каждое согласие является отдельным чекбоксом, не отмечено по умолчанию, рядом ссылка "Что это значит" с полным текстом. Без трех обязательных согласий отправка невозможна. Согласия даются в черновике; после отправки отозвать согласие можно только отменой заявки (`WITHDRAW`).

| Код | Название для клиента | Короткий текст у чекбокса | Срок действия | Обязательно |
|---|---|---|---|---|
| `CONSENT_PERSONAL_DATA` | Согласие на обработку персональных данных | Разрешаю банку обрабатывать персональные данные, указанные в заявке и полученные из госреестров (ФИО предпринимателя, руководителя, учредителей, поручителя), чтобы рассмотреть заявку и оформить кредит. | до достижения цели обработки | да |
| `CONSENT_CREDIT_BUREAU` | Согласие на запрос кредитной истории | Разрешаю банку запросить мою (компании) кредитную историю в бюро кредитных историй, чтобы оценить заявку. Банк увидит действующие и закрытые кредиты, платежи и просрочки. | 6 месяцев с момента согласия | да |
| `AUTHORITY_CONFIRMATION` | Подтверждение полномочий | Подтверждаю, что могу действовать от имени компании (ИП): подавать заявку, давать согласия и подписывать документы. | на время заявки | да |

Сущность `consent` (фиксация для аудита): `id`, `application_id`, `user_id`, `consent_type`, `subject_inn`, `text_version` (например `BKI-2026-10-v1`), `text_sha256`, `granted_at` (время сервера, UTC), `expires_at`, `revoked_at`, `ip_address`, `user_agent`. Класс RESTRICTED. Перед запросом в БКИ воркер проверяет, что согласие есть, не отозвано и `expires_at` больше текущего времени; иначе запрос не выполняется, а заявка уходит в `PROCESSING_ERROR` с кодом `CONSENT_MISSING` (такое возможно только при ошибке в данных, потому что без согласия отправка запрещена).

## 7. Данные, которые создает система

| Сущность | Ключевые поля | Класс |
|---|---|---|
| `application` | `id`, `application_number` (вида `A-000123`, для отображения), `client_user_id`, `status`, `version`, поля раздела 1 и 3, служебные поля из [application-states.md](application-states.md), раздел 2, `submitted_snapshot` (JSON), `final_product_code`, `final_amount`, `final_term_months`, `final_rate_percent`, `final_monthly_payment` | CONFIDENTIAL (содержит RESTRICTED-поля) |
| `scoring_result` | `application_id`, `score`, `grade`, `pd`, `factor_contributions[]`, `scorecard_version`, `calculated_at` | CONFIDENTIAL, клиенту не показывается |
| `decision` | `id`, `application_id`, `outcome`, `mode`, `status` (`PROPOSED`, `FINAL`, `REJECTED`), `reason_codes[]`, `rules_fired[]`, `recommendation`, `override`, `comment`, `proposed_by`, `decided_by`, `confirmed_by`, `scorecard_version`, `policy_version`, `created_at` | CONFIDENTIAL; клиенту показываются только исход, тексты причин и предложение |
| `offer` / `offer_option` | `offer`: `id`, `decision_id`, `expires_at`, `selected_option_id`; `offer_option`: `id`, `option_type` (`REQUESTED`, `AMOUNT_REDUCED`, `TERM_EXTENDED`, `PRODUCT_CHANGED`, `UNDERWRITER_TERMS`), `product_code`, `amount`, `term_months`, `rate_percent`, `monthly_payment`, `total_payment`, `overpayment`, `requires_owner_guarantee`, `requires_collateral`, `recommended`, для линии `tranche_max_term_months` | CONFIDENTIAL |
| `info_request` / `info_request_item` | `info_request`: `id`, `source` (`COMPLETENESS_CHECK`, `POLICY`, `UNDERWRITER`), `created_by`, `created_at`, `due_at`, `answered_at`; пункт: `id`, `reason_code` (`NI_*`), `answer_type` (`DOCUMENT`, `FIELD`, `TEXT`), `field_name` (для `FIELD`), `document_type` (для `DOCUMENT`), `client_text`, `required`, ответ (`answer_text`, `answer_value`, `document_ids[]`) | CONFIDENTIAL |
| `signing_code` | `id`, `application_id`, `code_hash` (код не хранится в открытом виде, кроме показа в момент выдачи), `documents_sha256[]`, `issued_at`, `expires_at`, `attempts`, `used_at` | SECRET |
| `signature` | `application_id`, `signing_code_id`, `documents_sha256[]`, `signed_at`, `ip_address`, `user_agent` | RESTRICTED |
| `loan` | `application_id`, `contract_number`, `account_number_masked`, `product_code`, `amount` или `limit`, `rate_percent`, `term_months`, `issued_at`, `first_payment_date`, `abs_operation_id` | CONFIDENTIAL |
| `notification` | `id`, `user_id`, `application_id`, `code` (`NTF_*`), `title`, `body`, `created_at`, `read_at` | CONFIDENTIAL |
| `event` (журнал и outbox) | см. [events.md](events.md) | INTERNAL, без ПДн в полезной нагрузке |

## 8. Классификация данных по чувствительности

| Класс | Что входит | Кто видит | Правила |
|---|---|---|---|
| PUBLIC | каталог продуктов, справочник целей, тексты кодов причин для клиента | все | без ограничений |
| INTERNAL | коды статусов и событий, версии конфигов, агрегированные метрики без идентификаторов клиентов | сотрудники банка | не публикуется наружу |
| CONFIDENTIAL | параметры и финансовые показатели заявки, данные о компании из источников, обороты (банковская тайна), балл и вклад факторов, решения, комментарии сотрудников, пороги политики | владелец заявки (только свои данные, без балла, порогов и внутренних комментариев), андеррайтер, риск-менеджер | доступ по ролям ([roles-and-permissions.md](roles-and-permissions.md)); просмотр карточки сотрудником журналируется |
| RESTRICTED | персональные данные (ФИО ИП, руководителя, учредителей, поручителя, ИНН ИП), кредитный отчет БКИ, документы клиента, согласия с IP и user agent, подписи | владелец заявки (свои), андеррайтер, риск-менеджер | не пишутся в технические логи и полезную нагрузку событий; в логах ИНН маскируется (`1234******56`); скачивание документов журналируется |
| SECRET | коды подписания, хеши паролей, ключи JWT, секреты окружения | никто из пользователей (код подписания видит только клиент в момент выдачи) | хранятся только в виде хеша или в переменных окружения; никогда не попадают в логи и ответы API, кроме однократного показа кода клиенту |

В MVP все данные синтетические. Сроки хранения и уничтожения ПДн в промышленной эксплуатации определяются требованиями 152-ФЗ и банковского регулирования; в MVP заявки не удаляются физически, терминальные статусы являются логическим закрытием.
