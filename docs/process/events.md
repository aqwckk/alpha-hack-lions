# Каталог доменных событий и уведомлений

Статус: **принято для реализации MVP**. События пишутся в журнал (outbox) в той же транзакции, что и изменение данных. Журнал служит одновременно аудитом (кто, что, когда, на основании чего), источником метрик продукта ([../research/07-metrics.md](../research/07-metrics.md)) и источником уведомлений в кабинете. Коды событий в UPPER_SNAKE; соответствие именам из исследования PM-1 приведено в разделе 4.

## 1. Общая структура события

| Поле | Тип | Описание |
|---|---|---|
| `event_id` | uuid | уникальный id, ключ идемпотентности потребителей |
| `event_type` | string | код из каталога (раздел 2) |
| `occurred_at` | timestamptz (UTC) | время события на сервере |
| `application_id` | uuid, nullable | заявка (пусто для событий подбора до создания заявки и событий входа) |
| `actor_type` | enum: `CLIENT`, `UNDERWRITER`, `RISK_MANAGER`, `SYSTEM`, `TIMER` | кто инициировал |
| `actor_id` | uuid, nullable | пользователь (для `SYSTEM` и `TIMER` пусто) |
| `correlation_id` | string | id запроса или задачи воркера, сквозной для логов |
| `application_version` | int, nullable | версия заявки после изменения |
| `payload` | JSON | данные события (раздел 2) |

Правила:

1. **В `payload` нет персональных данных и секретов**: только идентификаторы, коды, суммы, сроки, версии, длительности. ФИО, ИНН ИП, ответы БКИ, тексты комментариев и коды подписания в события не пишутся (комментарий хранится в своей таблице, в событии только его id).
2. События неизменяемы; удаление и редактирование запрещены (только вставка).
3. Каждая смена статуса пишет `STATUS_CHANGED` плюс доменное событие перехода из таблицы.
4. События подбора (`PRODUCT_WIZARD_STARTED`, `PRODUCT_SELECTED`) отправляет фронтенд в API продуктовой аналитики; они связываются с заявкой через `wizard_session_id`.

## 2. Каталог событий

### 2.1. Подбор и черновик

| Код | Когда возникает | Payload | Метрики |
|---|---|---|---|
| `PRODUCT_WIZARD_STARTED` | клиент открыл мастер подбора | `wizard_session_id` | конверсия подбора |
| `PRODUCT_SELECTED` | клиент нажал "Оформить" на карточке продукта | `wizard_session_id`, `product_code`, `purpose`, `amount`, `term_months`, `rank` (позиция карточки), `was_recommended` | конверсия подбора, доля выбора рекомендованного продукта (H1) |
| `APPLICATION_CREATED` | создан черновик (T-01) | `product_code`, `purpose`, `amount`, `term_months`, `wizard_session_id` | старт заявки (знаменатель North Star) |
| `PREFILL_COMPLETED` | автозаполнение по ИНН успешно | `applicant_type`, `fields_prefilled`, `fields_total`, `sources[]`, `latency_ms` | доля автозаполненных полей (H2) |
| `PREFILL_FAILED` | автозаполнение не удалось | `reason` (`NOT_FOUND`, `SOURCE_UNAVAILABLE`) | надежность, качество ввода ИНН |
| `EARLY_CHECK_WARNING_SHOWN` | предварительная проверка показала вероятный стоп-фактор | `product_code`, `reason_codes[]` | эффект ранней проверки (H3) |
| `CONSENT_GIVEN` / `CONSENT_REVOKED` | клиент отметил / снял согласие | `consent_type`, `text_version`, `expires_at` | аудит согласий |
| `DOCUMENT_UPLOADED` / `DOCUMENT_DELETED` | загрузка / удаление файла | `document_id`, `document_type`, `size_bytes`, `info_request_item_id` | аудит |
| `DOCUMENT_DOWNLOADED` | сотрудник скачал документ клиента | `document_id`, `document_type` | журнал доступа |

### 2.2. Прием, полнота, дозапрос

| Код | Когда возникает | Payload | Метрики |
|---|---|---|---|
| `APPLICATION_SUBMITTED` | T-03 | `product_code`, `purpose`, `amount`, `term_months`, `fill_duration_sec` (от создания черновика) | конверсия заполнения, время заполнения (H2), старт отсчета SLA |
| `COMPLETENESS_PASSED` | T-06 | `attempt` (номер прохождения) | прохождение полноты с первого раза |
| `COMPLETENESS_FAILED` | T-07, T-08 | `missing_items[]` (коды документов или полей) | доля заявок с возвратом (H5) |
| `INFO_REQUESTED` | T-07, T-21, T-29 | `info_request_id`, `source` (`COMPLETENESS_CHECK`, `POLICY`, `UNDERWRITER`), `items[]` (`reason_code`, `answer_type`), `due_at`, `cycle_number` | доля дозапросов, циклы дозапроса (H5) |
| `INFO_PROVIDED` | T-10 | `info_request_id`, `response_duration_sec`, `changed_fields[]` (имена полей) | время ответа клиента (H5) |

### 2.3. Обогащение, скоринг, решение

| Код | Когда возникает | Payload | Метрики |
|---|---|---|---|
| `SOURCE_REQUEST_SUCCEEDED` | ответ источника получен | `source`, `attempt`, `latency_ms`, `from_cache` | надежность интеграций, латентность |
| `SOURCE_REQUEST_FAILED` | попытка запроса неуспешна | `source`, `attempt`, `error_code` (`SOURCE_TIMEOUT`, `SOURCE_HTTP_5XX`, `SOURCE_INVALID_RESPONSE`), `latency_ms` | ошибки интеграций |
| `ENRICHMENT_RETRY_SCHEDULED` | T-14 | `failed_sources[]`, `retry_number`, `next_retry_at` | число ретраев |
| `ENRICHMENT_COMPLETED` | T-13 | `sources[]`, `duration_ms`, `retries_total` | время обогащения |
| `ENRICHMENT_FAILED` | T-16 | `failed_sources[]`, `retries_total`, `last_error_code` | заявки, ушедшие в ошибку (цель: 0 потерянных) |
| `SCORING_COMPLETED` | T-17 | `score`, `grade`, `pd`, `scorecard_version` | распределение грейдов, PSI |
| `STOP_FACTOR_TRIGGERED` | POL-01 сработало (по каждому коду) | `reason_code`, `policy_version` | доля отказов по стоп-факторам (H3, H7) |
| `DECISION_MADE` | T-19...T-23, T-27, T-29, T-30, T-31 | `decision_id`, `outcome` (`APPROVED`, `COUNTER_OFFER`, `NEEDS_INFO`, `MANUAL_REVIEW`, `DECLINED`), `mode` (`AUTO`, `MANUAL`), `reason_codes[]`, `policy_version`, `scorecard_version`, `grade`, `override`, `requested_amount`, `offered_amount_max`, `offered_term_months`, `options_count`, `time_from_submit_sec` | North Star, time to decision, доля авторешений (H9), структура исходов, доля контрпредложений (H6), доля переопределений |

### 2.4. Ручное рассмотрение

| Код | Когда возникает | Payload | Метрики |
|---|---|---|---|
| `MANUAL_REVIEW_QUEUED` | T-08, T-22 | `reason_codes[]`, `review_due_at` | поток в ручную очередь |
| `REVIEW_TAKEN` | T-25 | `assignee_id`, `wait_sec` (от постановки в очередь) | время ожидания в очереди |
| `REVIEW_ASSIGNED` | T-23 (закрепление после дозапроса) | `assignee_id` | |
| `REVIEW_RELEASED` | T-26 | `assignee_id`, `comment_id` | |
| `REVIEW_SLA_BREACHED` | таймер `REVIEW_SLA` | `review_due_at`, `assignee_id` | SLA ручного рассмотрения (H10) |
| `COMMENT_ADDED` | внутренний комментарий | `comment_id` | доля решений с комментарием (guardrail) |
| `FOUR_EYES_REQUESTED` / `FOUR_EYES_APPROVED` / `FOUR_EYES_REJECTED` | T-28 / T-31 / T-32 | `decision_id`, `proposed_by`, `confirmed_by`, `trigger` (`AUTHORITY_LIMIT`, `OVERRIDE`) | доля решений на согласовании |
| `APPLICATION_VIEWED` | сотрудник открыл карточку | `view_context` (`QUEUE`, `SEARCH`, `ERROR_LIST`) | журнал доступа к ПДн |

### 2.5. Предложение, подписание, выдача

| Код | Когда возникает | Payload | Метрики |
|---|---|---|---|
| `OFFER_ISSUED` | T-19, T-27, T-31 | `offer_id`, `options[]` (`option_type`, `product_code`, `amount`, `term_months`, `rate_percent`, `monthly_payment`), `expires_at` | |
| `OFFER_ACCEPTED` | T-33 | `offer_id`, `option_id`, `option_type`, `product_code`, `amount`, `term_months`, `decision_sec` (от выдачи предложения) | принятие предложения, принятие контрпредложения (H6), доля выбора кредитной линии |
| `OFFER_DECLINED` | T-34, T-38, T-46 | `offer_id`, `decline_reason_code` (`OD_*`, необязательно) | причины отказа клиентов от предложений |
| `OFFER_EXPIRED` | T-35, T-40 | `offer_id`, `stage` (`OFFER_PENDING`, `SIGNING`) | |
| `DOCUMENTS_PREPARED` | T-36 | `document_types[]`, `edo_operation_id` | |
| `SIGNING_CODE_ISSUED` | команда `REQUEST_SIGNING_CODE` | `signing_code_id`, `expires_at` (сам код не пишется) | |
| `SIGNING_CODE_REJECTED` | неверный или истекший код | `signing_code_id`, `attempt`, `reason` (`WRONG`, `EXPIRED`, `ATTEMPTS_EXCEEDED`) | безопасность подписания |
| `DOCUMENTS_SIGNED` | T-39 | `signing_code_id`, `documents_sha256[]` | конверсия предложение в подпись |
| `LOAN_ISSUED` | T-42 | `product_code`, `amount`, `term_months`, `rate_percent`, `abs_operation_id`, `operation_type` (`DISBURSEMENT`, `CREDIT_LINE_LIMIT`) | конверсия подпись в выдачу, сквозная конверсия |

### 2.6. Общие и технические

| Код | Когда возникает | Payload | Метрики |
|---|---|---|---|
| `STATUS_CHANGED` | любой переход | `from_status`, `to_status`, `transition_id` (T-xx), `command` или `trigger` | длительность пребывания в статусах, воронка |
| `APPLICATION_CANCELLED` | T-04, T-05, T-11, T-12, T-41, T-45 | `cancel_reason` (`CL_*`), `from_status` | отток на этапах |
| `PROCESSING_FAILED` | переходы в `PROCESSING_ERROR` | `failed_stage`, `last_error_code` | надежность |
| `PROCESSING_RETRIED` | T-44 | `failed_stage` | время восстановления |
| `CONFIG_VERSION_LOADED` | воркер или API загрузил версию конфига | `config_type` (`SCORECARD`, `POLICY`), `version`, `sha256` | аудит версий (H8) |
| `USER_LOGGED_IN` / `LOGIN_FAILED` | вход в систему | `role`, `reason` (для неуспеха) | безопасность |
| `AI_SUMMARY_GENERATED` | (Could) сформировано ИИ-резюме для андеррайтера | `model_name`, `latency_ms`, `fallback_used` | использование ИИ, см. [../product/ai-usage.md](../product/ai-usage.md) |

## 3. Метрики по событиям

Формулы из исследования PM-1, переписанные на коды каталога. Экран метрик риск-менеджера (Should, экран BK-06) показывает строки, помеченные "дашборд".

| Метрика | Формула | Гипотеза | Где |
|---|---|---|---|
| **North Star**: доля начатых заявок с понятным решением в SLA продукта | заявки с `DECISION_MADE[outcome in (APPROVED, COUNTER_OFFER, DECLINED)]`, у которых `time_from_submit_sec` не больше SLA продукта / заявки с `APPLICATION_CREATED` за период | все | дашборд |
| Time to decision | медиана `time_from_submit_sec` по итоговым `DECISION_MADE` | H9 | дашборд |
| Конверсия подбора | `APPLICATION_CREATED` / `PRODUCT_WIZARD_STARTED` (по `wizard_session_id`) | H1 | дашборд |
| Конверсия заполнения | `APPLICATION_SUBMITTED` / `APPLICATION_CREATED` | H2, H11 | дашборд |
| Время заполнения | медиана `fill_duration_sec` | H2 | дашборд |
| Доля автозаполненных полей | сумма `fields_prefilled` / сумма `fields_total` | H2 | отчет |
| Полнота с первого раза | заявки без `COMPLETENESS_FAILED` / `APPLICATION_SUBMITTED` | H2, H5 | отчет |
| Доля дозапросов и циклы | заявки с `INFO_REQUESTED` / `APPLICATION_SUBMITTED`; среднее `cycle_number` | H5 | дашборд |
| Доля авторешений | `DECISION_MADE[mode = AUTO, outcome in (APPROVED, COUNTER_OFFER, DECLINED)]` / все итоговые `DECISION_MADE` | H9 | дашборд |
| SLA ручного рассмотрения | доля ручных итоговых решений без `REVIEW_SLA_BREACHED` | H10 | дашборд |
| Структура исходов | распределение `outcome` итоговых решений | H6, H7 | дашборд |
| Принятие контрпредложений | `OFFER_ACCEPTED` по предложениям с исходом `COUNTER_OFFER` / такие `OFFER_ISSUED` | H6 | дашборд |
| Доля отказов по стоп-факторам | заявки с `STOP_FACTOR_TRIGGERED` / итоговые решения | H3, H7 | отчет |
| Доля переопределений | `DECISION_MADE[mode = MANUAL, override = true]` / ручные решения | guardrail | дашборд |
| Надежность интеграций | `SOURCE_REQUEST_FAILED` / все попытки по источникам; число `ENRICHMENT_RETRY_SCHEDULED`; заявки в `PROCESSING_ERROR` | B-3 | дашборд |
| Сквозная конверсия | `LOAN_ISSUED` / `APPLICATION_CREATED` | бизнес-результат | дашборд |

Итоговым решением считается `DECISION_MADE` с исходом `APPROVED`, `COUNTER_OFFER` или `DECLINED` в статусе `FINAL`; `NEEDS_INFO` и `MANUAL_REVIEW` являются промежуточными.

## 4. Соответствие именам событий из исследования

| Имя в [07-metrics.md](../research/07-metrics.md) | Код в каталоге |
|---|---|
| `product_wizard_started` | `PRODUCT_WIZARD_STARTED` |
| `product_selected` | `PRODUCT_SELECTED` |
| `application_started` | `APPLICATION_CREATED` |
| `prefill_completed` | `PREFILL_COMPLETED` |
| `consent_given` | `CONSENT_GIVEN` |
| `application_submitted` | `APPLICATION_SUBMITTED` |
| `completeness_passed` / `completeness_failed` | `COMPLETENESS_PASSED` / `COMPLETENESS_FAILED` |
| `info_requested` / `info_provided` | `INFO_REQUESTED` / `INFO_PROVIDED` |
| `enrichment_completed` / `enrichment_failed` | `ENRICHMENT_COMPLETED`; сбой одной попытки `SOURCE_REQUEST_FAILED`, окончательный сбой `ENRICHMENT_FAILED` |
| `stop_factor_triggered` | `STOP_FACTOR_TRIGGERED` |
| `scoring_completed` | `SCORING_COMPLETED` |
| `manual_review_assigned` | постановка в очередь `MANUAL_REVIEW_QUEUED`, взятие в работу `REVIEW_TAKEN` |
| `decision_made` (исходы `approved`, `counter_offer`, `rejected`) | `DECISION_MADE` (исходы `APPROVED`, `COUNTER_OFFER`, `DECLINED`) |
| `offer_accepted` / `offer_declined` | `OFFER_ACCEPTED` / `OFFER_DECLINED` |
| `documents_signed` | `DOCUMENTS_SIGNED` |
| `loan_issued` | `LOAN_ISSUED` |

## 5. Уведомления в продукте

Уведомления создаются только внутри продукта: колокольчик со счетчиком непрочитанных, лента уведомлений и баннер на странице заявки. Email, SMS и мессенджеры не используются (требование ТЗ). Уведомление создается в той же транзакции, что и переход.

### 5.1. Клиенту

| Код | Когда | Заголовок | Текст |
|---|---|---|---|
| `NTF_SUBMITTED` | T-03 | Заявка отправлена | Заявка {application_number} принята. Мы проверяем данные, это обычно занимает несколько минут. |
| `NTF_CHECK_DELAYED` | T-14 при первом повторе | Проверка займет чуть больше времени | Один из источников данных отвечает с задержкой. Мы повторим запрос автоматически, от вас ничего не нужно. |
| `NTF_INFO_REQUESTED` | T-07, T-21, T-29 | Нужны данные от вас | Чтобы продолжить рассмотрение заявки {application_number}, ответьте на {k} вопросов до {due_at}. |
| `NTF_REVIEW_STARTED` | T-25 | Заявку рассматривает специалист | Специалист банка начал рассмотрение. Решение до {review_due_at}. |
| `NTF_DECISION_APPROVED` | решение `APPROVED` | Заявка одобрена | Банк готов выдать {amount} на {term} мес. Примите условия до {expires_at}. |
| `NTF_DECISION_COUNTER_OFFER` | решение `COUNTER_OFFER` | Банк предлагает другие условия | Посмотрите варианты и выберите подходящий до {expires_at}. |
| `NTF_DECISION_DECLINED` | решение `DECLINED` | Решение по заявке | К сожалению, банк не может выдать кредит. Причина и что можно сделать указаны в заявке. |
| `NTF_OFFER_EXPIRING` | таймер `OFFER_EXPIRING_SOON` | Предложение скоро истечет | Предложение по заявке {application_number} действует до {expires_at}. |
| `NTF_OFFER_EXPIRED` | T-35, T-40 | Срок предложения истек | Вы можете подать новую заявку, данные компании подставятся автоматически. |
| `NTF_DOCUMENTS_READY` | T-36 | Документы готовы к подписанию | Проверьте договор и график платежей и подпишите их кодом подтверждения. |
| `NTF_SIGNING_CODE` | `REQUEST_SIGNING_CODE` | Код подтверждения | Ваш код: {code}. Действует 5 минут. Никому его не сообщайте. (В реальном продукте код приходил бы по защищенному каналу; в прототипе показывается здесь.) |
| `NTF_LOAN_ISSUED` | T-42 | Кредит выдан | {amount} перечислены на счет {account_masked}. Первый платеж {first_payment_date}. |
| `NTF_LIMIT_OPENED` | T-42, итоговый продукт `CREDIT_LINE` | Лимит кредитной линии открыт | Лимит {amount} открыт на счете {account_masked}. Деньги можно брать частями. |
| `NTF_APPLICATION_CLOSED` | T-12 | Заявка закрыта | Мы не получили ответ на запрос до {due_at}, поэтому заявка закрыта. Вы можете подать новую. |

Текст `NTF_SIGNING_CODE` после истечения кода заменяется на "Код больше не действует" (сам код из ленты удаляется).

### 5.2. Сотрудникам

| Код | Кому | Когда | Текст |
|---|---|---|---|
| `NTF_EMP_INFO_PROVIDED` | закрепленный андеррайтер | ответ клиента на дозапрос андеррайтера, заявка вернулась в `IN_REVIEW` | Клиент ответил на дозапрос по заявке {application_number}. |
| `NTF_EMP_APPROVAL_REQUESTED` | все риск-менеджеры | T-28 | Нужна проверка решения по заявке {application_number} (сумма {amount}). |
| `NTF_EMP_DECISION_RETURNED` | автор проекта решения | T-32 | Риск-менеджер вернул решение по заявке {application_number}: {comment_preview}. |
| `NTF_EMP_PROCESSING_ERROR` | все андеррайтеры | переход в `PROCESSING_ERROR` | Заявка {application_number} требует внимания: ошибка на этапе {failed_stage}. |
