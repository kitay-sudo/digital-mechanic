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

История чата по машине: `{"messages": [Message]}`.

### `DELETE /api/conversations/{vehicle_id}`

Очищает чат машины. Заявки и журнал остаются.

### `POST /api/chat`

Запрос:

```json
{"vehicle_id": "M333YK47", "session_id": "S-0005", "text": "Получи результат диагностики"}
```

`session_id` — выбранная в интерфейсе проверка. Кнопки интерфейса отправляют обычный текст, инструмент выбирает агент:

- «Получить результат диагностики» → `Получи результат диагностики`;
- «Создать заявку» → `Создай заявку на дефектовку`.

Ответ: поток `application/x-ndjson`, по одному JSON-событию на строку.

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
  "recommendation": "Не принимайте одну из формулировок как бесспорную. Уточните у специалиста...",
  "confirmed": true,
  "resolution": "Что решил заказчик, если расхождение подтверждено",
  "resolution_source": "откуда решение"
}
```

- `statements` — не меньше двух формулировок, каждая с дословной цитатой в `ref.quote`. `text` — пересказ одной фразой, может быть пустым.
- `confirmed: true` — расхождение из реестра `config/conflicts.json`, его добавляет код. `false` — его нашла модель, цитаты сверены кодом.
- `recommendation` задаёт код, модель её не пишет.

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

## Ошибки

Обычные запросы отвечают `{"detail": "текст"}` с кодом 4xx или 5xx. Текст на русском, его можно показать механику.

## Дополнения после кик-оффа 26.11

### Профиль механика в запросе чата

`POST /api/chat` и `POST /api/drafts/{id}/confirm` принимают необязательное поле:

```json
{"profile": {"language": "ru", "level": "novice"}}
```

- `language`: язык ответов агента. `ru` (по умолчанию), `uz` (узбекский), `tg` (таджикский), `hi` (хинди). Цитаты из руководства всегда остаются дословными на русском. Тексты, которые задаёт код (сбой записи, предупреждения, основание приоритета), остаются на русском.
- `level`: `novice` (новичок: с пояснениями терминов и простыми словами) или `expert` (опытный: коротко, только суть). По умолчанию `expert`.

`GET /api/config` дополнительно отдаёт списки для настроек:

```json
{
  "languages": [{"code": "ru", "label": "Русский"}, {"code": "uz", "label": "Oʻzbekcha"}, {"code": "tg", "label": "Тоҷикӣ"}, {"code": "hi", "label": "हिन्दी"}],
  "levels": [{"code": "expert", "label": "Опытный", "hint": "Коротко, только суть"}, {"code": "novice", "label": "Новичок", "hint": "С пояснениями и простыми словами"}]
}
```

### `GET /api/audit?limit=100`

Журнал обращений: кто что спросил, что ответил агент, на какие источники сослался. Новые сверху.

```json
{
  "items": [
    {
      "id": "m_12", "created_at": "...", "vehicle_id": "T792HO98", "vehicle_title": "Урал-5557-10",
      "session_id": "S-0043", "question": "Получи результат диагностики",
      "kind": "verdict", "answer": "Короткий вывод агента",
      "sources": [{"manual_id": "yamz236_re", "short": "РЭ ЯМЗ-236М2", "pdf_page": 19}],
      "tools": ["get_diagnosis", "get_vehicle_history", "search_manuals"],
      "ticket_id": null,
      "usage": {"input_tokens": 0, "output_tokens": 0, "cost_rub": 0, "duration_ms": 0, "llm_calls": 0, "model": "..."}
    }
  ]
}
```

`sources` без повторов. `ticket_id` заполнен у сообщения о созданной заявке.
