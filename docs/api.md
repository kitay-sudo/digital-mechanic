# API сервера «Цифровой механик»

Контракт между сервером (FastAPI, `backend/`) и интерфейсом (Next.js, `frontend/`). Все пути начинаются с `/api`. Интерфейс ходит на тот же адрес, с которого открыт: Next.js проксирует `/api/*` на сервер (`BACKEND_URL`).

## Справочные запросы

### `GET /api/config`

```json
{
  "llm": {"provider": "mock", "model": "mock-llm", "mock": true},
  "thresholds": {"confidence_min": 0.5},
  "priority_actions": {
    "high": "На дефектовку до выпуска в рейс",
    "medium": "Дефектовка на ближайшее ТО, работа под наблюдением",
    "low": "Машина работает, узел проверяется на следующей проверке"
  }
}
```

### `GET /api/fleet`

Сводка парка для режима главного механика и список для выбора машины. Список отсортирован по приоритету: карантин, внимание, норма.

```json
{
  "summary": {"total": 50, "ok": 30, "attention": 15, "quarantine": 5, "recheck": 4},
  "vehicles": [VehicleBrief]
}
```

`VehicleBrief`:

```json
{
  "vehicle_id": "M333YK47", "garage_no": "Г-105", "make": "МАЗ", "model": "МАЗ-5337",
  "title": "МАЗ-5337", "vehicle_type": "грузовой автомобиль",
  "engine_model": "ЯМЗ-236М2", "fuel": "дизель",
  "fleet_status": "quarantine",
  "needs_recheck": false,
  "priority": "high",
  "last_session": {
    "session_id": "S-0005", "checked_at": "2026-11-20T10:00:00+03:00",
    "status": "anomaly", "anomaly_type": "F08", "anomaly_title": "Дизельная топливоподача",
    "anomaly_score": 0.76, "confidence": 0.73, "signal_quality": "good"
  },
  "sessions_count": 4,
  "tickets": [{"ticket_id": "TKT-0001", "session_id": "S-0005", "created_at": "..."}]
}
```

- `fleet_status`: `ok` (норма), `attention` (требует внимания), `quarantine` (карантин).
- `needs_recheck`: последняя проверка со сбоем записи, нужна повторная запись. Такая машина попадает в `attention`.
- `priority`: `high`, `medium`, `low` или `null`.
- `title`: готовое название машины (у МАЗ с ЯМЗ-536 поле `model` равно `null`, тогда в `title` стоит марка).
- `summary.recheck` считает машины с `needs_recheck`, они уже входят в `attention`.

### `GET /api/vehicles/{vehicle_id}`

`VehicleBrief` плюс:

```json
{
  "sessions": [
    {
      "session_id": "S-0002", "checked_at": "...", "status": "normal",
      "anomaly_type": null, "anomaly_title": null, "anomaly_score": 0.13,
      "confidence": 0.82, "signal_quality": "good", "description": "...",
      "ticket_id": null
    }
  ],
  "manuals": [{"manual_id": "yamz236_rk", "designation": "236.01.01 РК", "title": "Руководство по ремонту", "short": "РК ЯМЗ-236", "pages": 287}],
  "trend": {"direction": "rising", "text": "Оценка отклонения растёт три проверки подряд"},
  "tickets": [Ticket]
}
```

Проверки идут от ранней к поздней. `trend.direction`: `rising`, `falling`, `stable`, `none`. 404, если машины нет.

`Ticket`:

```json
{"ticket_id": "TKT-0001", "vehicle_id": "...", "session_id": "S-0005", "created_at": "...",
 "anomaly_type": "F08", "conclusion": "...", "urgency": "high",
 "operations": ["..."], "spare_parts": ["..."],
 "references": [{"manual": "236.01.01 РК", "pdf_page": 112}]}
```

## Чат с агентом

### `GET /api/conversations/{vehicle_id}`

История чата по машине: `{"messages": [Message], "turn": "running" | "failed" | null}`.

`turn` — состояние хода агента по этой машине: `running` — агент ещё работает над запросом; `failed` — ход закончился ошибкой, которую механик ещё не видел; `null` — хода нет.

### `DELETE /api/conversations/{vehicle_id}`

Очищает чат машины. Заявки и журнал остаются.

### `GET /api/conversations/{vehicle_id}/turn`

Подключение к ходу, который начат раньше. Ход агента идёт на сервере в фоне и не зависит от соединения: механик ушёл со страницы, погас экран телефона или пропала связь — агент доработает, ответ ляжет в переписку. Интерфейс вызывает этот метод, когда в истории чата `turn` не `null`.

Ответ: тот же поток событий, что у `POST /api/chat`, с начала хода и до конца. Если хода нет, поток пустой.

### `DELETE /api/conversations/{vehicle_id}/turn`

Интерфейс показал механику ошибку хода. После этого `turn` становится `null`. На идущий ход не влияет.

### `POST /api/chat`

Запрос:

```json
{"vehicle_id": "M333YK47", "session_id": "S-0005", "text": "Получи результат диагностики"}
```

`session_id` — выбранная в интерфейсе проверка. Кнопки интерфейса отправляют обычный текст, инструмент выбирает агент:

- «Получить результат диагностики» → `Получи результат диагностики`;
- «Создать заявку» → `Создай заявку на дефектовку`.

Ответ: поток `application/x-ndjson`, по одному JSON-событию на строку. Обрыв соединения ход не останавливает. Пока по машине идёт ход, новый запрос по ней получает `409`.

| `type` | Поля | Смысл |
|---|---|---|
| `user` | `message` | Сообщение механика сохранено |
| `step` | `id`, `tool`, `title`, `status` (`running`, `done`, `error`), `detail` | Шаг агента. Событие с тем же `id` обновляет шаг |
| `message` | `message` | Готовое сообщение агента |
| `error` | `text` | Ошибка, показать механику |
| `done` | `usage` | Конец хода |

`usage`: `{"input_tokens": 0, "output_tokens": 0, "cost_rub": 0.0, "duration_ms": 0, "llm_calls": 0, "model": "...", "mock": true}`.

`Message`:

```json
{
  "id": "m_12", "role": "assistant", "created_at": "...", "session_id": "S-0005",
  "kind": "verdict",
  "text": "Короткий вывод для механика",
  "diagnosis": {"...поля ответа /diagnose...": "", "checked_at": "..."},
  "assessment": Assessment,
  "answer": Answer,
  "draft": Draft,
  "ticket": Ticket,
  "steps": [{"id": "s1", "tool": "get_diagnosis", "title": "Получаю результат проверки", "status": "done", "detail": "POST /diagnose → 200"}],
  "usage": {"...": ""}
}
```

`role`: `user` или `assistant`. У сообщения механика есть только `id`, `role`, `created_at`, `session_id`, `text`.

`kind` у агента:

| `kind` | Что показывать | Какие поля есть |
|---|---|---|
| `verdict` | Карточка результата проверки | `diagnosis`, `assessment`, возможно `answer` |
| `answer` | Ответ на вопрос | `answer` |
| `ticket_draft` | Черновик заявки с кнопкой подтверждения | `draft` |
| `ticket_created` | Заявка создана | `ticket` |
| `notice` | Простой текст (отказ, пояснение) | только `text` |

`Assessment`:

```json
{
  "outcome": "anomaly",
  "priority": "high", "priority_label": "высокий",
  "priority_action": "На дефектовку до выпуска в рейс",
  "basis": ["Базовая критичность типа F02: высокая", "Оценка отклонения 0,81: без поправки"],
  "flags": {"check_failed": false, "quality_warning": false, "low_confidence": false, "engine_mismatch": false},
  "warnings": ["Запись с помехами: вывод предварительный"],
  "ticket_allowed": true,
  "ticket_block_reason": null,
  "confidence_min": 0.5
}
```

`outcome`: `normal`, `anomaly`, `check_failed`. При `normal` и `check_failed` `priority` равен `null`.

`Answer` (порядок из ТЗ: наблюдения, гипотезы, проверки, возможный ремонт, источник, ограничения):

```json
{
  "summary": "Одна-две фразы",
  "observations": ["..."],
  "hypotheses": ["..."],
  "checks": [{"text": "...", "refs": [Ref]}],
  "repair": [{"text": "...", "refs": [Ref]}],
  "limitations": ["..."],
  "conflicts": [Conflict],
  "not_found": false,
  "recommendation_text": null
}
```

- `hypotheses` — инженерные гипотезы, не из руководства. В интерфейсе помечаются как гипотезы.
- `checks` и `repair` — только из руководства, у каждого пункта есть проверенные ссылки.
- `not_found: true` — в руководствах этого двигателя ответа нет.
- `conflicts` — расхождения между страницами или документами (правило П18). В старых сообщениях поля нет.
- У пункта `checks` и `repair` может стоять `disputed: true`: шаг повторяет формулировку, по которой документы расходятся.
- `recommendation_text` — текст рекомендации на дефектовку, когда заявку отправить нельзя. Его можно скопировать.

`Conflict`:

```json
{
  "topic": "В каком состоянии двигателя регулировать тепловые зазоры клапанов",
  "statements": [{"text": "", "ref": Ref}, {"text": "", "ref": Ref}],
  "recommendation": "Работайте по более осторожной формулировке и уточните у производителя...",
  "confirmed": true,
  "resolution": "Как поступить, если расхождение согласовано с технической службой",
  "resolution_source": "кто и когда согласовал"
}
```

- `statements` — не меньше двух формулировок, каждая с дословной цитатой в `ref.quote`. `text` — пересказ одной фразой, может быть пустым.
- `confirmed: true` — расхождение из реестра `config/conflicts.json`, его добавляет код. `false` — его нашла модель, цитаты сверены кодом.
- `recommendation` задаёт код, модель её не пишет. Если есть `resolution`, экран показывает её вместо `recommendation` в блоке «Как поступить».

`Ref`:

```json
{"manual_id": "yamz236_rk", "designation": "236.01.01 РК", "short": "РК ЯМЗ-236", "pdf_page": 112, "quote": "дословная цитата со страницы"}
```

`Draft`:

```json
{
  "draft_id": "d_7", "vehicle_id": "...", "session_id": "S-0005", "status": "draft",
  "anomaly_type": "F02", "anomaly_title": "Низкое давление масла",
  "conclusion": "...", "urgency": "high", "urgency_basis": ["..."],
  "operations": [{"text": "...", "refs": [Ref]}],
  "spare_parts": [{"text": "...", "refs": [Ref]}],
  "references": [{"manual": "236.01.01 РК", "manual_id": "yamz236_rk", "pdf_page": 112}],
  "requires_warning_ack": false,
  "warnings": [],
  "ticket_id": null
}
```

`status`: `draft`, `sent`, `cancelled`.

### `PATCH /api/drafts/{draft_id}`

Правка черновика механиком: `{"conclusion": "...", "urgency": "medium"}`. Можно прислать одно поле. Ответ: `Draft`. 409, если заявка уже отправлена.

### `POST /api/drafts/{draft_id}/confirm`

Подтверждение показанного состава: `{"warning_ack": true}`. `warning_ack` обязателен и равен `true`, когда `requires_warning_ack`. Ответ: такой же поток событий, как у `/api/chat`; в нём приходит сообщение `ticket_created` или `error`.

## Руководства

### `GET /api/manuals/{manual_id}/pages/{page}`

```json
{"manual_id": "yamz236_rk", "designation": "236.01.01 РК", "title": "Руководство по ремонту двигателей ЯМЗ-236М2",
 "short": "РК ЯМЗ-236", "engine": "ЯМЗ-236М2", "page": 112, "page_count": 287,
 "image_url": "/api/manuals/yamz236_rk/pages/112/image", "text": "..."}
```

### `GET /api/manuals/{manual_id}/pages/{page}/image?q=цитата`

PNG страницы. С параметром `q` цитата подсвечена на картинке. Ширина около 1400 px.

## Служебное

- `GET /api/health` → `{"status": "ok", "ml": true, "toir": true, "kb": {"manuals": 6, "pages": 1743, "chunks": 0}}`
- `GET /api/usage/summary?since=` → средние токены и стоимость сценария с разбивкой по шагам, для шаблона расчёта. `since` (время ISO) оставляет только более поздние ходы.
- `GET /api/usage/export.xlsx?from=&to=&model=&vehicle_id=&mechanic=&vat=` → расчёт стоимости в xlsx по шаблону организаторов, с формулами. `from`, `to`: `ГГГГ-ММ-ДД` или `ГГГГ-ММ-ДДTЧЧ:ММ:СС` по времени хода, конец включается целиком; `mechanic` — фамилия из профиля; `vat` — НДС в ценах настроек, % (по умолчанию 5 для цен в ₽, 0 для $). Неверная дата — 400.

## Ошибки

Обычные запросы отвечают `{"detail": "текст"}` с кодом 4xx или 5xx. Текст на русском, его можно показать механику.

## Дополнения после кик-оффа 26.11

### Профиль механика в запросе чата

Агент отвечает только на русском языке, выбора языка нет.

`POST /api/chat` и `POST /api/drafts/{id}/confirm` принимают необязательное поле:

```json
{"profile": {"level": "novice"}}
```

- `level`: `novice` (новичок: с пояснениями терминов и простыми словами) или `expert` (опытный: коротко, только суть). По умолчанию `expert`.

`GET /api/config` дополнительно отдаёт список уровней подачи для настроек:

```json
{
  "levels": [{"code": "expert", "label": "Опытный", "hint": "Коротко, только суть"}, {"code": "novice", "label": "Новичок", "hint": "С пояснениями и простыми словами"}]
}
```

### `GET /api/audit`

Журнал обращений целиком, постранично с сервера: кто что спросил, что ответил агент, на какие источники сослался. Новые сверху.

Параметры: `page` (с 1), `page_size` (до 100; старый `limit` — размер страницы), `from`, `to` (дата `2026-11-27` — сутки по местному времени, конец включительно, или время `2026-11-27T08:00`), `vehicle_id`, `mechanic` (автор вопроса или сообщения о проблеме, без учёта регистра), `type` (`report`, `no_answer`, `kb_missing`, `ml_mismatch`, `injection`), `status` (`all`, `open` — новые и в работе, `new`, `in_work`, `reviewed`), `q` (поиск по тексту вопроса, ответа и сообщения механика).

```json
{
  "items": [
    {
      "id": "m_12", "source": "answer", "created_at": "...", "vehicle_id": "T792HO98", "vehicle_title": "Урал-5557-10",
      "engine_model": "ЯМЗ-236М2", "session_id": "S-0043", "question": "Получи результат диагностики",
      "author": "Иванов", "photos": 0, "kind": "verdict", "answer": "Короткий вывод агента",
      "sources": [{"manual_id": "yamz236_re", "short": "РЭ ЯМЗ-236М2", "pdf_page": 19}],
      "tools": ["get_diagnosis", "get_vehicle_history", "search_manuals"],
      "ticket_id": null,
      "usage": {"input_tokens": 0, "output_tokens": 0, "cost_rub": 0, "duration_ms": 0, "llm_calls": 0, "model": "..."},
      "report": {"reason": "Ответ неверный", "text": "...", "author": "Петров", "created_at": "..."}, "reports_count": 1,
      "gap": {"type": "report", "label": "От механика", "title": "...", "status": "new", "status_label": "Новый", "reviewed_at": null},
      "status": "new", "repeats": 1, "injection": false
    }
  ],
  "total": 52, "page": 1, "page_size": 20, "gaps_open": 5,
  "facets": {"vehicles": [{"vehicle_id": "T792HO98", "title": "Урал-5557-10"}], "mechanics": ["Иванов", "Петров"]}
}
```

`sources` без повторов. `ticket_id` заполнен у сообщения о созданной заявке. Строка — группа повторов: одинаковые вопросы без ответа в руководстве по одной модели двигателя (текст сравнивается без регистра, лишних пробелов и знаков) и повторные сообщения механиков на один ответ; `repeats` — сколько раз повторилось, поля — последнего повтора. `gap` и `status` есть только у случаев, которые разбирает администратор. `id` вида `a_3` — вопрос механика администратору (`source: "admin"`, ответа агента нет). `injection` — в описании от ML-сервиса был посторонний текст.

### `GET /api/audit/gaps`

`{"open": 5}` — сколько случаев «новый» и «в работе» (группа повторов — один случай): число у пункта «Журнал».

### `GET /api/audit/{id}`

Карточка случая: поля строки журнала и `details` (`summary`, `checks`, `repair`, `limitations`, `recommendation_text`, `warnings`, `anomaly_title`), `reports` (все сообщения механиков), `occurrences` (повторы: `id`, `created_at`, `vehicle_id`, `author`), `history` (`status`, `status_label`, `comment`, `reviewer`, `at`), `comment`, `reviewer`, `updated_at`.

### `POST /api/audit/status`

```json
{"ids": ["m_12", "a_3"], "status": "in_work", "comment": "Запросили производителя", "reviewer": "Сидоров"}
```

Статус `new`, `in_work` или `reviewed` у нескольких строк сразу; отмечается вся группа повторов каждой строки. `comment` не передан — комментарий прежний. `reviewer` пока приходит из интерфейса. Ответ: `{"updated": 3, "at": "...", "gaps_open": 4}`. Новое сообщение механика по разобранному ответу и новый повтор вопроса возвращают случай в «новый». Старый `POST /api/audit/{id}/review {"reviewed": true}` работает поверх статусов.

### `GET /api/audit/digest?day=2026-11-27`

Текст сводки администратору за день (по умолчанию сегодня) и `mode`, `time`, `sent_at`, `cases`, `open_total`. Режим уведомлений `ALERT_MODE`: `digest` (по умолчанию) — сразу на `ALERT_WEBHOOK_URL` уходят только `kb_missing`, `ml_mismatch` и сбои агента, остальное одной сводкой в `DIGEST_TIME` (18:00) по `APP_TZ` (Europe/Moscow); `instant` — всё сразу.

### `POST /api/admin-messages`

```json
{"vehicle_id": "T792HO98", "text": "Нет щупа нужного размера на посту 2", "author": "Петров"}
```

Вопрос механика администратору напрямую, не к ответу агента. `vehicle_id` и `author` необязательны, `text` от 1 до 1000 символов. Ответ `{"id": "a_3", "created_at": "..."}`. В журнале — случай «От механика» без ответа агента, уведомление как у сообщения о проблеме.

### `GET /api/shift-summary?from=...&to=...`

Сводка смены (по умолчанию сегодня): `totals` (`questions`, `answers`, `vehicles`, `marks`, `tickets`, `open_cases` за период, `open_total` всего), `mechanics` (`name`, `questions`, `marks`, `messages`, `first_at`, `last_at`), `marks` (`vehicle_id`, `step`, `list`, `index`, `author`, `at`), `tickets` (`ticket_id`, `vehicle_id`, `created_at`, `urgency`, `conclusion`).

### `GET /api/metrics?from=...&to=...`

Метрики пилота за период (по умолчанию сегодня): `verdict_to_ticket` (`count`, `avg_min`, `median_min` — от первого вердикта по проверке до создания заявки), `refusals` (`answers`, `not_found`, `share`), `repeat_after_repair` (вердикты с предупреждением «Повтор после ремонта»), `verdicts`, `response` (`count`, `avg_ms`), `cost` (`total_rub`, `per_answer_rub`, `speech_rub`).

## Вход и роли

Без входа открыты только `GET /api/health`, `GET /api/config`, маршруты `/api/auth/*` и документация `/api/docs`. Остальные `/api/*` отвечают `401`, если нет сессии. Сессия — подписанная кука `dm_session` (httpOnly, SameSite=Lax), прокси интерфейса передаёт её на сервер. Разделы администратора (`/api/audit*`, `/api/usage*`, `/api/shift-summary`, `/api/metrics`, `/api/admin/*`) механику отвечают `403`. `AUTH_REQUIRED=0` выключает проверку. Действующий ключ `X-API-Key` из `INTEGRATION_API_KEYS` открывает все маршруты (служебный доступ).

- `GET /api/auth/me` → `{"required": true, "role": "mechanic", "mechanic": {"id": 1, "full_name": "Иванов Иван", "level": "expert", "font_size": "normal"}, "hint": "Демо: Иванов, PIN 1111"}`. `role` — `mechanic`, `admin` или `null`.
- `GET /api/auth/mechanics` → `{"items": [{"id": 1, "full_name": "Иванов Иван"}], "hint": …}`: список экрана «Кто работает», только работающие.
- `POST /api/auth/mechanic` `{"mechanic_id": 1, "pin": "1111"}` → `200` и кука. Неверный PIN: `401 {"detail", "attempts_left"}`; пятая ошибка подряд и минута после неё: `429 {"detail", "retry_after"}`.
- `POST /api/auth/admin` `{"login", "password"}` → `200` и кука; `401` — неверно, `429` — пять ошибок подряд, вход закрыт на минуту.
- `POST /api/auth/logout` → кука удаляется.

Экраны администратора:

- `GET /api/admin/mechanics`, `POST /api/admin/mechanics`, `PUT /api/admin/mechanics/{id}` — те же поля и ответы, что у `/api/v1/mechanics` ([docs/integration.md](integration.md)).
- `GET /api/admin/integrations`, `PUT /api/admin/integrations` — как `/api/v1/settings/integrations`, плюс `health`: есть ли связь с ML-сервисом и ТОиР.

API для внешних систем (`/api/v1`, ключ `X-API-Key`): [docs/integration.md](integration.md), документация с проверкой запросов — `/api/docs`.
