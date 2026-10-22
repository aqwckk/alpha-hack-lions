# API кредитного конвейера

REST API на JSON для веб-кабинета клиента и рабочего места сотрудника банка. Контракт: [openapi.json](openapi.json) (экспорт из FastAPI командой `make openapi`), интерактивная документация Swagger UI: `http://localhost:8000/api/docs` (через веб-интерфейс: `http://localhost:8080/api/docs`). Коллекции запросов основного сценария: [postman_collection.json](postman_collection.json) и [requests.http](requests.http).

Процессная модель, на которую опирается API: [статусы и переходы T-xx](../process/application-states.md), [роли и права](../process/roles-and-permissions.md), [модель решения](../process/decision-model.md), [данные заявки](../process/data-requirements.md), [события](../process/events.md).

## 1. Общие правила

| Тема | Правило |
|---|---|
| Базовый URL | `/api/v1/...`; служебные `/api/health/live`, `/api/health/ready`; метрики Prometheus `/metrics` (только внутри сети, nginx его не публикует) |
| Формат | JSON в UTF-8. Деньги передаются строкой с двумя знаками (`"1200000.00"`), на вход допускается целое число рублей. Ставки строкой в процентах годовых (`"22.00"`). Время в ISO 8601 UTC (`2026-10-23T09:00:00Z`), даты `YYYY-MM-DD`. Для показа клиенту API дополнительно отдает готовые тексты с датами по Москве (`"до 24 октября, 18:00"`) |
| Версия API | префикс `/v1`; несовместимые изменения выпускаются как `/v2`. Версии скоринговой карты и политики не связаны с версией API и пишутся в каждое решение (`scorecard_version`, `policy_version`) |
| Идентификатор запроса | заголовок `X-Request-Id` (можно передать свой, иначе генерируется); возвращается в ответе и в теле ошибки, сквозной для логов api, воркера и симулятора |
| Пагинация | `?page=1&page_size=20` (максимум 100, для журнала аудита 200); ответ `{items, page, page_size, total}` |
| Обновление статуса | клиентский экран опрашивает `GET /applications/{id}` каждые 3 секунды в статусах `SENT`, `CHECKING`, `DOCUMENTS`, `PAYOUT` и каждые 15 секунд в остальных нетерминальных ([screens.md](../product/screens.md), раздел 1) |

## 2. Аутентификация и роли

1. `POST /api/v1/auth/login` с `{"login", "password"}` возвращает `access_token` (JWT HS256, срок 30 минут), `expires_in` и профиль пользователя (`role`, `full_name`, ИНН компаний клиента). Одновременно ставится HttpOnly-cookie `refresh_token` (SameSite=Strict, путь `/api/v1/auth`, 12 часов).
2. Все остальные запросы: заголовок `Authorization: Bearer <access_token>`. Роль берется только из токена, выданного сервером, и сверяется с пользователем в БД при каждом запросе.
3. `POST /api/v1/auth/refresh` (cookie) выдает новую пару; refresh-токен одноразовый, повторное использование отзывает всю цепочку. `POST /api/v1/auth/logout` отзывает цепочку и удаляет cookie. `GET /api/v1/auth/me` возвращает профиль.
4. После 5 неудачных попыток входа для логина вход приостанавливается на 1 минуту (`429 LOGIN_RATE_LIMITED`, заголовок `Retry-After`), есть и ограничение по IP. Ответ на неверный логин и неверный пароль одинаковый.

Роли: `CLIENT` (представитель бизнеса), `UNDERWRITER` (андеррайтер), `RISK_MANAGER` (риск-менеджер, принцип 4 глаз, метрики, аудит). Тестовые учетные записи (синтетические, пароли публичные, источник `analytics/artifacts/demo_users.json`):

| Логин | Пароль | Роль | Сценарий |
|---|---|---|---|
| `client.irina` | `Demo-Client-2026` | CLIENT | S1 автоодобрение |
| `client.andrey` | `Demo-Client-2026` | CLIENT | S2 контрпредложение |
| `client.marina` | `Demo-Client-2026` | CLIENT | S3 дозапрос и ручное рассмотрение |
| `client.sergey` | `Demo-Client-2026` | CLIENT | S4 отказ по стоп-факторам |
| `client.oleg` | `Demo-Client-2026` | CLIENT | S5 сбой внешнего сервиса |
| `client.demo` | `Demo-Client-2026` | CLIENT | 7 дополнительных профилей и любой корректный ИНН |
| `uw.dmitry`, `uw.anna` | `Demo-Uw-2026` | UNDERWRITER | очередь, решения, гонка "Взять в работу" |
| `risk.elena` | `Demo-Risk-2026` | RISK_MANAGER | 4 глаза, все заявки, метрики, версии, аудит |

## 3. Команды над заявкой: версия, идемпотентность, доступные действия

* **`available_actions`.** Каждый ответ с заявкой содержит список команд, которые текущий пользователь может выполнить сейчас. Он вычисляется из той же декларативной таблицы переходов, которой проверяются команды (`app/domain/statemachine.py`). Интерфейс показывает кнопки только из этого списка. Коды: `UPDATE_DRAFT`, `PREFILL_BY_INN`, `GIVE_CONSENT`, `REVOKE_CONSENT`, `UPLOAD_DOCUMENT`, `DELETE_DOCUMENT`, `SUBMIT`, `RESPOND_INFO`, `WITHDRAW`, `ACCEPT_OFFER`, `DECLINE_OFFER`, `REQUEST_SIGNING_CODE`, `SIGN`, `TAKE`, `RELEASE`, `APPROVE`, `MAKE_COUNTER_OFFER`, `REQUEST_INFO`, `DECLINE`, `CONFIRM_DECISION`, `RETURN_DECISION`, `RETRY_PROCESSING`, `ADD_COMMENT`.
* **`expected_version`.** Команды, меняющие заявку, передают в теле версию, которую видел пользователь. Если заявка изменилась, ответ `409 VERSION_CONFLICT` с `details.current_version`; если команда недопустима в текущем статусе, `409 INVALID_TRANSITION`. Смена статуса выполняется одним условным `UPDATE ... WHERE status = :from AND version = :expected`.
* **`Idempotency-Key`.** Обязателен для команд, меняющих статус (создание, отправка, ответ на дозапрос, отмена, принятие и отказ от предложения, код и подпись, все решения сотрудников). Повтор с тем же ключом и тем же телом возвращает сохраненный ответ с заголовком `Idempotent-Replayed: true` и не выполняет команду второй раз; тот же ключ с другим телом дает `422 IDEMPOTENCY_KEY_REUSED`. Ошибочная команда ключ не занимает. Ключи хранятся 24 часа. Для автосохранения черновика ключ необязателен.

## 4. Ресурсы

### 4.1. Каталог и подбор (клиент)

| Метод и путь | Назначение |
|---|---|
| `GET /api/v1/catalog/products` | продукты активной политики: границы, ставки, требования, обязательные документы |
| `GET /api/v1/catalog/dictionaries` | цели, типы документов, полные тексты согласий с версией и хешем, причины отказа от предложения, роли представителя, типы залога |
| `POST /api/v1/catalog/match` | подбор по задаче: `{purpose, amount, term_months, applicant_type?, inn?}`; карточки с пометкой "Рекомендуем", платеж и переплата по базовой ставке, требования; с ИНН ранняя проверка возраста бизнеса (`available=false`, `eligible_date`) |
| `POST /api/v1/catalog/calculate` | аннуитетный платеж, итого и переплата; `with_schedule=true` добавляет график |
| `POST /api/v1/analytics/events` | события мастера подбора `PRODUCT_WIZARD_STARTED`, `PRODUCT_SELECTED` (`wizard_session_id`) для метрик конверсии |

### 4.2. Заявка клиента

| Метод и путь | Команда | Что важно |
|---|---|---|
| `GET /api/v1/applications` | | только свои заявки: номер, продукт, сумма, `client_status`, заголовок, `next_action_label` |
| `POST /api/v1/applications` | `CREATE_APPLICATION` (T-01) | `{product_code, purpose, amount, term_months, wizard_session_id}`; `CREDIT_LINE` напрямую нельзя (`422 PRODUCT_NOT_DIRECT`) |
| `GET /api/v1/applications/{id}` | | полный клиентский вид (раздел 5) |
| `PATCH /api/v1/applications/{id}` | `UPDATE_DRAFT` (T-02) | автосохранение: меняются только переданные поля, `null` очищает поле; поля с ошибкой формата возвращаются в `field_errors`, остальные сохраняются |
| `POST /api/v1/applications/{id}/prefill` | `PREFILL_BY_INN` | `{inn?, expected_version?}`: сведения ЕГРЮЛ/ЕГРИП и ФНС из моков (блок `company`), ранние предупреждения `early_warnings`; результат `FOUND`, `NOT_FOUND` или `SOURCE_UNAVAILABLE` (можно продолжать) |
| `PUT` / `DELETE /api/v1/applications/{id}/consents/{type}` | `GIVE_CONSENT` / `REVOKE_CONSENT` | `CONSENT_PERSONAL_DATA`, `CONSENT_CREDIT_BUREAU` (6 месяцев), `AUTHORITY_CONFIRMATION`; фиксируются время сервера, версия и хеш текста, IP, user agent |
| `POST /api/v1/applications/{id}/documents` | `UPLOAD_DOCUMENT` | multipart: `document_type`, `file`, `info_request_item_id` (в `INFO_REQUESTED`), PDF/JPG/PNG по сигнатуре файла, до 10 МБ, до 20 файлов |
| `GET .../documents/{doc_id}/content`, `DELETE .../documents/{doc_id}` | `DELETE_DOCUMENT` | удаление только в черновике |
| `POST /api/v1/applications/{id}/submit` | `SUBMIT` (T-03) | полная проверка полей продукта, согласий, ИНН, дубликата активной заявки (`409 DUPLICATE_ACTIVE_APPLICATION`) |
| `POST /api/v1/applications/{id}/info-response` | `RESPOND_INFO` (T-10) | `{expected_version, answers: [{item_id, answer_text?, answer_value?, document_ids?}]}`; ответы на все обязательные пункты |
| `POST /api/v1/applications/{id}/withdraw` | `WITHDRAW` (T-04, T-11, T-41, T-45) | |
| `POST /api/v1/applications/{id}/offer/accept` | `ACCEPT_OFFER` (T-33) | `{expected_version, option_id}`; после `expires_at` ответ `409 OFFER_EXPIRED` |
| `POST /api/v1/applications/{id}/offer/decline` | `DECLINE_OFFER` (T-34, T-38, T-46) | `{expected_version, reason_code?}` из `OD_*` |
| `GET /api/v1/applications/{id}/schedule?option_id=` | | график платежей варианта или выданного кредита |
| `GET /api/v1/applications/{id}/signing-documents/{doc_id}` | | текст документа от мока ЭДО перед подписанием |
| `POST /api/v1/applications/{id}/signing-code` | `REQUEST_SIGNING_CODE` | 6 цифр, 5 минут, прежний код аннулируется, не больше 5 кодов в час; в демо-режиме код приходит в ответе и в уведомлении `NTF_SIGNING_CODE` |
| `POST /api/v1/applications/{id}/sign` | `SIGN` (T-39) | `{expected_version, code}`; неверный код: `422 SIGNING_CODE_INVALID` с `details.attempts_left`, после 3 попыток код аннулируется |
| `POST /api/v1/applications/{id}/explain` | | "Объяснить проще": шаблон, с включенным ИИ переформулировка локальной моделью без изменения чисел |

### 4.3. Уведомления (все роли)

`GET /api/v1/notifications?unread_only=` (лента и счетчик `unread`), `POST /api/v1/notifications/{id}/read`, `POST /api/v1/notifications/read-all`. Коды `NTF_*` из [events.md](../process/events.md), раздел 5. Других каналов (email, SMS) нет.

### 4.4. Рабочее место сотрудника

| Метод и путь | Роль | Назначение |
|---|---|---|
| `GET /api/v1/bank/applications?tab=` | UW, RM | вкладки `queue` (MANUAL_REVIEW по сроку SLA), `mine`, `errors` (PROCESSING_ERROR), `decided`, `approval` и `all` (только RM); фильтры `status`, `product_code`, `outcome`, `mode`, `number`, `inn`, `created_from`, `created_to`, `include_history`; счетчики вкладок `counters`. Черновики не видны никому |
| `GET /api/v1/bank/applications/{id}?view_context=` | UW, RM | карточка: анкета и снимок при отправке, изменения полей после дозапросов, сведения реестров, ответы каждого источника с попытками и временем, расхождения, скоринг по факторам, путь правил политики со значениями, рекомендация, решения с версиями, предложение, документы, согласия, дозапросы, комментарии, полная история событий; для RM журнал аудита по заявке. Каждое открытие пишет `APPLICATION_VIEWED` |
| `POST .../take` | UW | `TAKE` (T-25); проигравший в гонке получает `409 ALREADY_TAKEN` с именем коллеги |
| `POST .../release` | UW, исполнитель | `RELEASE` (T-26), комментарий обязателен |
| `POST .../approve` | UW, исполнитель | одобрение на запрошенных условиях (T-27 или T-28 при 4 глазах) |
| `POST .../counter-offer` | UW, исполнитель | `{options: [{product_code?, amount, term_months}] (1-3), comment}`; ставка из матрицы по грейду |
| `POST .../request-info` | UW, исполнитель | `{items: [{reason_code NI_*, answer_type, field_name?, document_type?, client_text?, required}] (1-10), comment}` |
| `POST .../decline` | UW, исполнитель | `{reason_codes: SF_*/DCL_* (кроме DCL_AFFORDABILITY), comment}` |
| `POST .../confirm`, `POST .../return` | RM, не автор проекта | `CONFIRM_DECISION` (T-31), `RETURN_DECISION` (T-32, комментарий обязателен) |
| `POST .../retry` | UW, RM | `RETRY_PROCESSING` (T-44): возврат в `failed_stage` и повтор задачи этапа |
| `POST .../comments` | UW, RM | внутренний комментарий, клиенту не виден |
| `GET .../documents/{doc_id}/content` | UW, RM | скачивание документа клиента (пишется `DOCUMENT_DOWNLOADED`) |
| `POST .../ai-summary` | UW, RM | резюме для андеррайтера: блоки `risks`, `checks`, `positives`, пометка "Сформировано автоматически" |
| `GET /api/v1/bank/dictionaries` | UW, RM | коды для диалогов решения: причины отказа, пункты дозапроса, поля и типы документов |

### 4.5. Риск-менеджер

| Метод и путь | Назначение |
|---|---|
| `GET /api/v1/risk/metrics?period_days=30&product_code=` (или `from`, `to`) | метрики экрана BK-06 по журналу событий: North Star, time to decision, воронка, доля авторешений, SLA ручной очереди, структура исходов, принятие предложений и контрпредложений, переопределения, надежность интеграций, распределение и PSI грейдов, ориентиры `targets` ([metrics.md](../analytics/metrics.md)) |
| `GET /api/v1/risk/configs` | активные версии скоринговой карты и политики (версия, sha256, автор, дата) и история загрузок; доступно и андеррайтеру |
| `GET /api/v1/risk/configs/{SCORECARD или POLICY}` | параметры активной версии только для чтения |
| `GET /api/v1/risk/audit` | журнал аудита: кто, что, когда, откуда (`access_only=true`: просмотры карточек и скачивания) |

### 4.6. Демо-управление симулятором (только `DEMO_MODE=true`, сотрудники)

`GET /api/v1/demo/integrations` (состояние), `POST /api/v1/demo/integrations/reset` (сброс счетчиков сбоев: сценарий S5 можно показать снова), `PUT /api/v1/demo/integrations/outage` `{source, failure: "TIMEOUT" | "HTTP_500" | null}` (глобальное отключение источника для S5b).

## 5. Что получает клиент

`GET /api/v1/applications/{id}` (схема `ClientApplication`) строго ограничен списком полей: в нем нет внутреннего статуса, балла, грейда, PD, вклада факторов, пути правил, рекомендации, порогов, исполнителя и внутренних комментариев. Ключевые поля:

| Поле | Смысл |
|---|---|
| `client_status` | `FILLING`, `SENT`, `CHECKING`, `ACTION_REQUIRED`, `SPECIALIST_REVIEW`, `DECISION_READY`, `DOCUMENTS`, `PAYOUT`, `COMPLETED`, `REJECTED`, `WITHDRAWN`, `EXPIRED` |
| `client_status_text` | `title`, `what_is_happening`, `what_next`, `deadline_text`, `deadline_at`, `notes` (например "Инвестиционные кредиты всегда рассматривает специалист.") |
| `progress_step`, `progress[]` | 8 шагов с состоянием `DONE`, `CURRENT`, `ACTION_REQUIRED`, `PENDING`, `SKIPPED` ("не потребовался"), `STOPPED` |
| `available_actions`, `version` | что можно сделать и с какой версией |
| `form`, `company`, `early_warnings`, `warnings` | анкета, сведения из госреестров (только чтение), предупреждения ранней проверки и полей |
| `consents`, `documents`, `required_documents` | состояние согласий и документов |
| `info_request` | открытый дозапрос: пункты с текстом "зачем", типом ответа, текущим значением поля, сроком |
| `offer` | `outcome`, `expires_at`, блок "Вы просили" (`requested`), тексты причин, варианты (`option_type`, сумма, срок, ставка, платеж, переплата, требования, `recommended`, `difference_text`, для линии `credit_line`) |
| `decision` | при отказе: тексты причин и следующих шагов по правилам видимости FULL/GENERIC/NONE |
| `final_terms`, `signing`, `loan` | итоговые условия, документы на подпись и активный код, выданный кредит |
| `timeline`, `notifications` | история смены клиентского статуса, уведомления по заявке |

## 6. Ошибки

Единый формат:

```json
{"error": {"code": "VERSION_CONFLICT", "message": "Заявка изменилась, обновите данные", "request_id": "6f1c...", "details": {"current_version": 7}, "fields": [{"field": "amount", "code": "OUT_OF_RANGE", "message": "Для этого продукта допустимо от 300 000 руб. до 5 000 000 руб."}]}}
```

| HTTP | Код | Когда |
|---|---|---|
| 400 | `IDEMPOTENCY_KEY_REQUIRED`, `IDEMPOTENCY_KEY_INVALID` | нет или некорректен `Idempotency-Key` |
| 401 | `UNAUTHORIZED`, `TOKEN_INVALID`, `INVALID_CREDENTIALS`, `REFRESH_*` | нет токена, истек, неверный вход |
| 403 | `ROLE_NOT_ALLOWED`, `NOT_ASSIGNEE`, `FOUR_EYES_SAME_USER`, `COMPANY_ACCESS_DENIED`, `DEMO_DISABLED` | роль не подходит, не исполнитель, автор проекта решения, компания закреплена за другим представителем |
| 404 | `NOT_FOUND`, `DOCUMENT_NOT_FOUND` | нет объекта или нет доступа (чужая заявка клиента всегда 404) |
| 409 | `INVALID_TRANSITION`, `VERSION_CONFLICT`, `DUPLICATE_ACTIVE_APPLICATION`, `ALREADY_TAKEN`, `OFFER_EXPIRED`, `SCORING_REQUIRED`, `DOCUMENTS_NOT_READY`, `IDEMPOTENCY_IN_PROGRESS` | конфликт состояния |
| 413 | `PAYLOAD_TOO_LARGE` | тело больше лимита (1 МБ для JSON, 11 МБ для документов) |
| 422 | `VALIDATION_FAILED` (с `fields`), `DOCUMENT_TOO_LARGE`, `DOCUMENT_TYPE_NOT_ALLOWED`, `PRODUCT_NOT_DIRECT`, `SIGNING_CODE_INVALID`, `SIGNING_CODE_EXPIRED`, `SIGNING_ATTEMPTS_EXCEEDED`, `IDEMPOTENCY_KEY_REUSED` | ошибка данных; тексты полей из [data-requirements.md](../process/data-requirements.md), раздел 1.2 |
| 429 | `LOGIN_RATE_LIMITED`, `SIGNING_CODE_LIMIT`, `TOO_MANY_REQUESTS` | ограничение частоты |
| 503 | `SERVICE_UNAVAILABLE`, `SIGNING_SERVICE_UNAVAILABLE`, `MOCK_UNAVAILABLE` | зависимость недоступна, повторите позже |

Для клиента `INVALID_TRANSITION` содержит `details.current_client_status`, для сотрудника `details.current_status`.

## 7. Пример: сценарий S1 через curl

```bash
API=http://localhost:8000/api
TOKEN=$(curl -s $API/v1/auth/login -H 'Content-Type: application/json' \
  -d '{"login":"client.irina","password":"Demo-Client-2026"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')
AUTH="Authorization: Bearer $TOKEN"

# подбор и черновик
curl -s $API/v1/catalog/match -H "$AUTH" -H 'Content-Type: application/json' -d '{"purpose":"EQUIPMENT","amount":"1200000","term_months":24}'
APP=$(curl -s $API/v1/applications -H "$AUTH" -H "Idempotency-Key: $(uuidgen)" -H 'Content-Type: application/json' \
  -d '{"product_code":"EXPRESS","purpose":"EQUIPMENT","amount":"1200000","term_months":24}')
ID=$(echo "$APP" | python3 -c 'import sys,json;print(json.load(sys.stdin)["id"])')

# автозаполнение по ИНН, поля, согласия (version берем из последнего ответа)
curl -s $API/v1/applications/$ID/prefill -H "$AUTH" -H 'Content-Type: application/json' -d '{"inn":"002000010193","expected_version":1}'
curl -s -X PATCH $API/v1/applications/$ID -H "$AUTH" -H 'Content-Type: application/json' \
  -d '{"expected_version":2,"representative_role":"OWNER","monthly_revenue_declared":"1500000","existing_monthly_payments_declared":"0"}'
for C in CONSENT_PERSONAL_DATA CONSENT_CREDIT_BUREAU AUTHORITY_CONFIRMATION; do
  curl -s -X PUT $API/v1/applications/$ID/consents/$C -H "$AUTH" > /dev/null; done

# отправка: версия из GET, затем опрос до DECISION_READY
V=$(curl -s $API/v1/applications/$ID -H "$AUTH" | python3 -c 'import sys,json;print(json.load(sys.stdin)["version"])')
curl -s $API/v1/applications/$ID/submit -H "$AUTH" -H "Idempotency-Key: $(uuidgen)" -H 'Content-Type: application/json' -d "{\"expected_version\":$V}"
```

Полный путь до выдачи с обеими ролями: [requests.http](requests.http), Postman-коллекция или `python3 scripts/e2e_demo.py`.

## 8. Служебные эндпоинты

| Путь | Что проверяет |
|---|---|
| `GET /api/health/live` | процесс жив (healthcheck контейнера) |
| `GET /api/health/ready` | доступна БД, загружены скоринговая карта и политика ожидаемых версий; иначе 503 |
| `GET /metrics` | Prometheus: запросы и задержки по маршрутам, переходы T-xx, события, вызовы внешних систем; у воркера свой `/metrics` на порту 9100 (задачи, длительность, очередь) |
