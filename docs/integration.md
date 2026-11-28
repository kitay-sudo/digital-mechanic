# Подключение внешних систем

API для учётной системы парка, «НейроДВС», кадровой системы и 1С. Все методы под `/api/v1`, ответы в JSON, ошибки с понятным текстом по-русски в поле `detail`. Документация с проверкой запросов в браузере: `/api/docs`, на стенде [digital-mechanic.ru/api/docs](https://digital-mechanic.ru/api/docs).

## Оглавление

1. [Как подключиться](#1-как-подключиться)
2. [Коды ответов](#2-коды-ответов)
3. [Машины: учётная система парка](#3-машины-учётная-система-парка)
4. [Проверки: веб-хук «НейроДВС»](#4-проверки-веб-хук-нейродвс)
5. [Коннектор к агенту](#5-коннектор-к-агенту)
6. [Механики: кадровая система](#6-механики-кадровая-система)
7. [Настройки подключений](#7-настройки-подключений)
8. [Служебный доступ](#8-служебный-доступ)
9. [Приёмник заявок: переходник под 1С](#9-приёмник-заявок-переходник-под-1с)

## 1. Как подключиться

1. Администратор сервера задаёт в `.env` ключи, по ключу на каждую систему, через запятую, и перезапускает сервер. Без ключей API выключен и отвечает `503`.
2. Система передаёт ключ в заголовке каждого запроса: `X-API-Key: <ключ>`.
3. В `/api/docs` кнопка Authorize принимает ключ, описание OpenAPI 3.1 для генерации клиента лежит в `/api/openapi.json`. Оба адреса открываются и через интерфейс (порт 3000), и напрямую на сервере агента (порт 8000).

Строка в `.env` сервера.
```ini
INTEGRATION_API_KEYS=<ключ учётной системы>,<ключ НейроДВС>,<ключ 1С>
```

Создать ключ: длинную случайную строку.
```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

В примерах ниже адрес API и ключ лежат в переменных оболочки.

Задать адрес API.
```bash
API=http://localhost:3000/api/v1
```

Задать ключ.
```bash
KEY=<ключ>
```

## 2. Коды ответов

| Код | Когда |
|:---|:---|
| `200` | готово; для `POST`: запись уже была и обновлена |
| `201` | создана новая запись |
| `400` | нужен явный признак, например `warning_ack` для записи с помехами |
| `401` | нет заголовка `X-API-Key` |
| `403` | ключ не подходит |
| `404` | нет машины, проверки, механика или черновика |
| `409` | конфликт: агент ещё отвечает по этой машине, такой механик уже есть, заявка уже отправлена |
| `422` | поля не прошли проверку: текст в `detail`, по полям в `errors`, допустимые значения в `allowed` |
| `502` | сбой модели или внешнего сервиса, причина в `detail` |
| `503` | API выключен: на сервере не задан `INTEGRATION_API_KEYS` |

Пример ошибки:
```json
{
  "detail": "Модель двигателя «Д-245» не найдена в реестре руководств. Допустимые: ЗМЗ-40904.10, ЗМЗ-40905.10, ЗМЗ-5234.10, ЯМЗ-236М2, ЯМЗ-536.",
  "field": "engine_model",
  "allowed": ["ЗМЗ-40904.10", "ЗМЗ-40905.10", "ЗМЗ-5234.10", "ЯМЗ-236М2", "ЯМЗ-536"]
}
```

## 3. Машины: учётная система парка

Парк хранится в базе приложения. При первом запуске база наполняется из `vehicles.json` материалов задачи; повторный запуск добавляет только то, чего в базе нет, правки учётной системы не перетираются. Госномер служит ключом машины: пробелы и регистр не важны, похожие буквы кириллицы переводятся в латиницу (`а 777 мм 77` → `A777MM77`).

Модель двигателя берётся только из реестра руководств (`config/manuals.json`): агент отвечает строго по руководствам двигателя машины, поэтому машину с двигателем без руководств завести нельзя.

Узнать допустимые модели двигателей.
```bash
curl -H "X-API-Key: $KEY" $API/engines
```

Создать или обновить машину по госномеру: `201` новая, `200` обновлены переданные поля.
```bash
curl -X POST -H "X-API-Key: $KEY" -H "Content-Type: application/json" $API/vehicles -d '{"vehicle_id": "A123BC77", "garage_no": "Г-150", "make": "МАЗ", "model": "МАЗ-5337", "vehicle_type": "грузовой автомобиль", "engine_model": "ЯМЗ-236М2", "fuel": "дизель"}'
```

Получить список машин вместе с выведенными из парка.
```bash
curl -H "X-API-Key: $KEY" "$API/vehicles?include_inactive=true"
```

Получить одну машину.
```bash
curl -H "X-API-Key: $KEY" $API/vehicles/A123BC77
```

Изменить поля: меняются только переданные.
```bash
curl -X PUT -H "X-API-Key: $KEY" -H "Content-Type: application/json" $API/vehicles/A123BC77 -d '{"garage_no": "Г-151", "engine_model": "ЯМЗ-536"}'
```

Вывести машину из парка: она пропадает из сводки и чата, история и заявки сохраняются. Вернуть её можно запросом `POST /vehicles` с тем же госномером.
```bash
curl -X DELETE -H "X-API-Key: $KEY" $API/vehicles/A123BC77
```

## 4. Проверки: веб-хук «НейроДВС»

«НейроДВС» сообщает, что проверка готова. Проверка сразу появляется в истории машины и в сводке парка. Повтор веб-хука с тем же `session_id` безопасен: ответ `200`, данные обновляются.

Сообщить о проверке без результата: сервер сам запросит его у ML-сервиса (`POST /diagnose`).
```bash
curl -X POST -H "X-API-Key: $KEY" -H "Content-Type: application/json" $API/checks -d '{"vehicle_id": "A123BC77", "session_id": "S-1001", "checked_at": "2026-11-27T10:30:00+03:00"}'
```

Сообщить о проверке с полным результатом: агент использует его, когда ML-сервис эту проверку не знает или недоступен.
```bash
curl -X POST -H "X-API-Key: $KEY" -H "Content-Type: application/json" $API/checks -d '{"vehicle_id": "A123BC77", "session_id": "S-1002", "checked_at": "2026-11-27T11:05:00+03:00", "status": "anomaly", "anomaly_type": "F02", "anomaly_title": "Повышенный стук клапанов", "anomaly_score": 0.71, "confidence": 0.83, "signal_quality": "good", "description": "Периодический стук в зоне ГРМ на холостом ходу", "model_version": "neurodvs-2.3"}'
```

Если результат передан, обязательны `status` и `signal_quality`, при `status=anomaly` ещё `anomaly_type`. Пока результата нет, проверка видна в истории, а статус машины в сводке считается по последней проверке с результатом.

## 5. Коннектор к агенту

Тот же ход агента, что в чате: ответ пишется в переписку по машине и в журнал, но приходит одним JSON, когда агент закончил, обычно за 10-60 секунд. По одной машине одновременно идёт один ход: второй запрос получит `409`.

Разобрать результат проверки; без `session_id` берётся последняя проверка.
```bash
curl -X POST -H "X-API-Key: $KEY" -H "Content-Type: application/json" $API/agent/diagnose -d '{"vehicle_id": "A123BC77", "session_id": "S-1002", "mechanic": "Иванов Иван"}'
```

Задать вопрос по руководству.
```bash
curl -X POST -H "X-API-Key: $KEY" -H "Content-Type: application/json" $API/agent/ask -d '{"vehicle_id": "A123BC77", "text": "Какой тепловой зазор клапанов?", "mechanic": "Иванов Иван", "level": "novice"}'
```

Попросить черновик заявки: ответ `kind=ticket_draft`, в ТОиР ещё ничего не ушло.
```bash
curl -X POST -H "X-API-Key: $KEY" -H "Content-Type: application/json" $API/agent/ask -d '{"vehicle_id": "A123BC77", "session_id": "S-1002", "text": "Создай заявку на дефектовку"}'
```

Подтвердить черновик от имени механика: заявка уходит в ТОиР, ответ `kind=ticket_created` с номером.
```bash
curl -X POST -H "X-API-Key: $KEY" -H "Content-Type: application/json" $API/agent/confirm -d '{"draft_id": "d_12", "mechanic": "Иванов Иван"}'
```

Поля ответа:

| Поле | Что в нём |
|:---|:---|
| `kind` | вид ответа, значения ниже |
| `text` | главная фраза ответа |
| `diagnosis` | результат проверки от ML-сервиса |
| `assessment` | оценка правилами: исход, приоритет и основание, можно ли оформить заявку и почему нет |
| `answer` | пункты `checks` и `repair` со ссылками `refs`: документ, страница PDF, цитата; `not_found`: ответа нет |
| `draft`, `ticket` | черновик заявки и созданная заявка |
| `steps`, `usage` | шаги агента, токены, стоимость и время ответа |

Значения `kind`:

- **`verdict`.** Разбор проверки.
- **`answer`.** Ответ по руководству.
- **`ticket_draft`.** Черновик заявки ждёт подтверждения.
- **`ticket_created`.** Заявка создана в ТОиР.
- **`notice`.** Сообщение, например почему заявка не отправлена.

## 6. Механики: кадровая система

Механик выбирает себя в списке «Кто работает» и входит своим PIN. После входа к нему применяются размер шрифта и подача ответов. PIN хранится только хэшем с солью, в ответах его нет. `font_size`: `normal` обычный, `large` крупный. `level`: `expert` опытный, коротко; `novice` новичок, с пояснениями.

Завести механика.
```bash
curl -X POST -H "X-API-Key: $KEY" -H "Content-Type: application/json" $API/mechanics -d '{"full_name": "Кузнецов Андрей Павлович", "age": 45, "font_size": "normal", "level": "expert", "pin": "4821"}'
```

Получить список механиков.
```bash
curl -H "X-API-Key: $KEY" $API/mechanics
```

Получить одного механика.
```bash
curl -H "X-API-Key: $KEY" $API/mechanics/4
```

Изменить механика: новый PIN или отключение завершают его вход на всех устройствах.
```bash
curl -X PUT -H "X-API-Key: $KEY" -H "Content-Type: application/json" $API/mechanics/4 -d '{"font_size": "large", "pin": "7305"}'
```

Отключить механика: он пропадает из списка входа, его подписи в чате и журнале остаются. Вернуть можно запросом `PUT` с `"active": true`.
```bash
curl -X DELETE -H "X-API-Key: $KEY" $API/mechanics/4
```

## 7. Настройки подключений

Адреса ML-сервиса и ТОиР, веб-хук администратора и токены доступа (`Authorization: Bearer`). Значения хранятся в базе, перекрывают `.env` и действуют сразу. Администратор меняет их и в интерфейсе, на экране «Подключения».

Получить текущие настройки.
```bash
curl -H "X-API-Key: $KEY" $API/settings/integrations
```

Задать адреса и токен.
```bash
curl -X PUT -H "X-API-Key: $KEY" -H "Content-Type: application/json" $API/settings/integrations -d '{"ml_url": "https://ml.neurodvs.example/api", "ml_token": "<токен>", "toir_url": "https://toir.example/api", "alert_webhook_url": "https://chat.example/hooks/abc123"}'
```

Вернуть значение из `.env`: передать пустую строку.
```bash
curl -X PUT -H "X-API-Key: $KEY" -H "Content-Type: application/json" $API/settings/integrations -d '{"ml_url": ""}'
```

Секреты в ответе скрыты: у токенов видны только последние 4 знака, у веб-хука скрыт путь, у адресов скрыты пароль и значения параметров. Скрытое значение, отправленное обратно, не сохраняется. Поле `source`: `db` задано здесь, `env` взято из `.env`.

## 8. Служебный доступ

Остальные маршруты сервера (`/api/fleet`, `/api/chat` и другие) закрыты входом механика или администратора. Действующий ключ `X-API-Key` открывает и их: так работают скрипты проверки качества и сводка стоимости.

Получить сводку стоимости по журналу.
```bash
curl -H "X-API-Key: $KEY" http://localhost:8000/api/usage/summary
```

## 9. Приёмник заявок: переходник под 1С

Подтверждённую механиком заявку отправляет приёмник заявок (`TicketSink` в `backend/app/clients.py`). Сейчас это HTTP-сервис ТОиР по контракту ТЗ: `POST {toir_url}/tickets`, ответ `201` с `ticket_id`. Под другую учётную систему пишется один класс с двумя методами и подключается строкой в `.env`, остальной код не меняется:

```ini
TICKET_SINK=app.sinks.onec:OneCSink
```

Контракт:

- `create(payload) -> {"ticket_id": str, "status": str}`. `payload`: заявка по разделу 5 ТЗ, `vehicle_id`, `session_id`, `anomaly_type`, `conclusion`, `urgency` (`low`, `medium`, `high`), `operations` и `spare_parts` (списки строк), `references` (`[{"manual", "pdf_page"}]`).
- Если система заявку не приняла: `ServiceError("текст для механика", status)`. Механик увидит причину; повторно агент заявку не отправит.
- `health() -> bool`: доступна ли система (`/api/health`, экран «Подключения»).
- Конструктор получает настройки (`Settings`): адрес `toir_url` и токен `toir_token` берутся из «Подключений» или `.env`.

Заготовка под HTTP-сервис 1С:ТОиР (публикация на веб-сервере, базовая аутентификация), файл `backend/app/sinks/onec.py`. Имена документа и полей замените на свои из конфигурации:

```python
import base64

import httpx

from app.clients import ServiceError
from app.config import Settings

URGENCY = {"low": "Низкая", "medium": "Средняя", "high": "Высокая"}


class OneCSink:
    """Заявка на дефектовку как документ «Заявка на ремонт» в 1С:ТОиР через HTTP-сервис."""

    name = "1c"

    def __init__(self, settings: Settings):
        self.url = settings.toir_url  # например https://1c.example/toir/hs/mechanic
        self.auth = settings.toir_token  # «логин:пароль» пользователя 1С для обмена

    def _headers(self) -> dict:
        token = base64.b64encode(self.auth.encode()).decode()
        return {"Authorization": f"Basic {token}"} if self.auth else {}

    async def create(self, payload: dict) -> dict:
        document = {
            "ОбъектРемонта": payload["vehicle_id"],
            "НомерДиагностики": payload["session_id"],
            "ВидДефекта": payload["anomaly_type"],
            "Описание": payload["conclusion"],
            "Срочность": URGENCY[payload["urgency"]],
            "Работы": [{"Наименование": op} for op in payload["operations"]],
            "Материалы": [{"Наименование": part} for part in payload["spare_parts"]],
            "Основание": "; ".join(f"{r['manual']}, стр. {r['pdf_page']}" for r in payload["references"]),
        }
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                resp = await client.post(f"{self.url}/repair-requests", json=document, headers=self._headers())
        except httpx.HTTPError as exc:
            raise ServiceError(f"Нет связи с 1С ({self.url}): {exc.__class__.__name__}") from exc
        if resp.status_code == 401:
            raise ServiceError("1С не приняла логин и пароль обмена: проверьте токен в «Подключениях»", 401)
        if resp.status_code >= 400:
            raise ServiceError(f"1С не приняла заявку ({resp.status_code}): {resp.text[:300]}", resp.status_code)
        data = resp.json()
        return {"ticket_id": data["Номер"], "status": "created"}

    async def health(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=3) as client:
                return (await client.get(f"{self.url}/ping", headers=self._headers())).status_code == 200
        except httpx.HTTPError:
            return False
```

Переходник проверяется теми же тестами, что ТОиР: в `tests/conftest.py` фикстура `services` подменяет `clients.create_ticket` и сверяет состав заявки с контрактом.
