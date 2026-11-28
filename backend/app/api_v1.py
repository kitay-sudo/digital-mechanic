"""API для внешних систем: /api/v1. Документация: /api/docs (OpenAPI: /api/openapi.json).

Доступ по заголовку X-API-Key, ключи в INTEGRATION_API_KEYS через запятую. Без ключей API выключен (503).
- учётная система парка ведёт машины: /api/v1/vehicles;
- «НейроДВС» сообщает о готовой проверке: /api/v1/checks (веб-хук);
- кадровая система или администратор ведут механиков: /api/v1/mechanics;
- настройки подключений: /api/v1/settings/integrations;
- коннектор к агенту: /api/v1/agent/diagnose, /api/v1/agent/ask, /api/v1/agent/confirm.

Здесь же маршруты экранов администратора (/api/admin/*, вход по куке, см. auth.py): они вызывают те же функции.
Подробно с примерами: docs/integration.md.
"""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, FastAPI, Query, Request, Security
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from . import auth, clients, demo, fleet, integrations, mechanics, turns
from .version import VERSION
from .agent.loop import run_turn
from .config import get_settings
from .fleet_db import RESULT_FIELDS
from .manuals import all_manuals, manuals_for_engine

log = logging.getLogger("mechanic")


# --- ошибки ---
class ApiError(Exception):
    """Ошибка с понятным текстом: ответ {"detail": текст, ...дополнительные поля}."""

    def __init__(self, status: int, message: str, **extra):
        super().__init__(message)
        self.status = status
        self.extra = extra


async def _api_error(_: Request, exc: ApiError) -> JSONResponse:
    return JSONResponse({"detail": str(exc), **exc.extra}, status_code=exc.status)


def _translate(err: dict) -> str:
    kind, ctx = err.get("type", ""), err.get("ctx") or {}
    if kind == "missing":
        return "обязательное поле"
    if kind == "string_too_short":
        return f"не короче {ctx.get('min_length', 1)} знаков"
    if kind == "string_too_long":
        return f"не длиннее {ctx.get('max_length')} знаков"
    if kind == "string_pattern_mismatch":
        return "неверный формат"
    if kind in ("string_type",):
        return "нужна строка"
    if kind in ("int_parsing", "int_type", "int_from_float"):
        return "нужно целое число"
    if kind in ("float_parsing", "float_type"):
        return "нужно число"
    if kind in ("bool_parsing", "bool_type"):
        return "нужно true или false"
    if kind == "greater_than_equal":
        return f"не меньше {ctx.get('ge')}"
    if kind == "less_than_equal":
        return f"не больше {ctx.get('le')}"
    if kind == "literal_error":
        return f"допустимые значения: {ctx.get('expected')}"
    if kind.startswith("datetime") or kind.startswith("date_"):
        return "нужны дата и время ISO 8601, например 2026-11-27T10:30:00+03:00"
    if kind == "json_invalid":
        return "тело запроса — не JSON"
    if kind in ("model_attributes_type", "dict_type", "model_type"):
        return "нужен объект JSON"
    if kind == "extra_forbidden":
        return "неизвестное поле"
    if kind == "value_error":
        return str(err.get("msg", "")).removeprefix("Value error, ")
    return str(err.get("msg", "неверное значение"))


async def _validation_error(request: Request, exc: RequestValidationError):
    if not request.url.path.startswith(("/api/v1", "/api/admin", "/api/auth")):
        return await request_validation_exception_handler(request, exc)
    errors = []
    for err in exc.errors():
        loc = [str(p) for p in err.get("loc", ()) if p not in ("body", "query", "path")]
        errors.append({"field": ".".join(loc) or "тело запроса", "message": _translate(err)})
    text = "; ".join(f"{e['field']}: {e['message']}" for e in errors)
    return JSONResponse({"detail": f"Запрос не прошёл проверку. {text}", "errors": errors}, status_code=422)


# --- ключ доступа ---
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False, description="Ключ из INTEGRATION_API_KEYS")


async def require_key(key: str | None = Security(api_key_header)) -> None:
    if not auth.api_keys():
        raise ApiError(503, "API для внешних систем выключен: на сервере не задан ни один ключ. "
                            "Администратору: впишите ключи в INTEGRATION_API_KEYS (через запятую) и перезапустите сервер.")
    if not key:
        raise ApiError(401, "Нужен ключ доступа: передайте его в заголовке X-API-Key.")
    if not auth.key_valid(key):
        raise ApiError(403, "Ключ доступа не подходит. Проверьте значение заголовка X-API-Key.")


class Error(BaseModel):
    detail: str = Field(description="Что не так, по-русски: текст можно показать человеку")


class FieldError(BaseModel):
    field: str
    message: str


class ValidationErrorOut(Error):
    errors: list[FieldError] = Field(default_factory=list, description="Ошибки по полям")
    field: str | None = Field(default=None, description="Поле с ошибкой, если оно одно")
    allowed: list[str] | None = Field(default=None, description="Допустимые значения (модель двигателя)")


ERRORS = {
    401: {"model": Error, "description": "Нет заголовка X-API-Key"},
    403: {"model": Error, "description": "Ключ не подходит"},
    422: {"model": ValidationErrorOut, "description": "Поля запроса не прошли проверку: текст в detail, по полям в errors"},
    503: {"model": Error, "description": "API выключен: на сервере не заданы ключи"},
}
v1 = APIRouter(prefix="/api/v1", dependencies=[Depends(require_key)], responses=ERRORS)
admin = APIRouter(prefix="/api/admin", include_in_schema=False)


# --- нормализация ---
# Похожие буквы кириллицы и латиницы: в госномере — латиница (как в данных заказчика), в модели двигателя — кириллица
CYR_TO_LAT = str.maketrans("АВЕКМНОРСТУХ", "ABEKMHOPCTYX")
LAT_TO_CYR = str.maketrans("ABEKMHOPCTYX", "АВЕКМНОРСТУХ")
PLATE_RE = re.compile(r"^[A-Z0-9]{4,12}$")


def plate(value: str) -> str:
    out = re.sub(r"[\s\-]", "", value.upper()).translate(CYR_TO_LAT)
    if not PLATE_RE.match(out):
        raise ValueError("госномер — от 4 до 12 знаков: цифры и буквы А, В, Е, К, М, Н, О, Р, С, Т, У, Х")
    return out


def engines() -> list[str]:
    return sorted({e for m in all_manuals() for e in m.engines})


def canonical_engine(value: str) -> str:
    """Модель двигателя из реестра руководств (config/manuals.json). Регистр и похожие латинские буквы не важны."""
    key = re.sub(r"\s", "", value.upper()).translate(LAT_TO_CYR)
    for engine in engines():
        if re.sub(r"\s", "", engine.upper()).translate(LAT_TO_CYR) == key:
            return engine
    raise ApiError(422, f"Модель двигателя «{value}» не найдена в реестре руководств. Допустимые: {', '.join(engines())}. "
                        "Чтобы добавить двигатель, нужны его руководства в базе знаний (config/manuals.json).",
                   field="engine_model", allowed=engines())


def vehicle_or_404(vehicle_id: str, include_inactive: bool = False) -> dict:
    try:
        vid = plate(vehicle_id)
    except ValueError as exc:
        raise ApiError(422, f"Госномер «{vehicle_id}»: {exc}", field="vehicle_id") from exc
    record = fleet.repo().record(vid)
    if record is None or (not record["active"] and not include_inactive):
        raise ApiError(404, f"Машины {vid} нет в парке. Сначала заведите её: POST /api/v1/vehicles.")
    return record


def _with_manuals(record: dict) -> dict:
    return {**record, "manuals": [m.short for m in manuals_for_engine(record["engine_model"])]}


# --- машины ---
class VehicleFields(BaseModel):
    model_config = ConfigDict(extra="forbid")

    garage_no: str | None = Field(default=None, max_length=30, description="Гаражный номер", examples=["Г-101"])
    make: str | None = Field(default=None, max_length=60, description="Марка", examples=["МАЗ"])
    model: str | None = Field(default=None, max_length=80, description="Модель", examples=["МАЗ-5337"])
    vehicle_type: str | None = Field(default=None, max_length=60, description="Тип машины",
                                     examples=["грузовой автомобиль"])
    fuel: str | None = Field(default=None, max_length=30, description="Топливо", examples=["дизель"])


class VehicleIn(VehicleFields):
    model_config = ConfigDict(extra="forbid", json_schema_extra={"examples": [{
        "vehicle_id": "A123BC77", "garage_no": "Г-150", "make": "МАЗ", "model": "МАЗ-5337",
        "vehicle_type": "грузовой автомобиль", "engine_model": "ЯМЗ-236М2", "fuel": "дизель",
    }]})

    vehicle_id: str = Field(min_length=4, max_length=20, description="Госномер: ключ машины. Пробелы и регистр не важны, "
                            "кириллица переводится в латиницу", examples=["A123BC77"])
    engine_model: str | None = Field(default=None, min_length=2, max_length=40,
                                     description="Модель двигателя из реестра руководств (GET /api/v1/engines). "
                                     "Обязательна для новой машины", examples=["ЯМЗ-236М2"])

    @field_validator("vehicle_id")
    @classmethod
    def _plate(cls, v: str) -> str:
        return plate(v)


class VehiclePatch(VehicleFields):
    model_config = ConfigDict(extra="forbid", json_schema_extra={"examples": [{"garage_no": "Г-151", "engine_model": "ЯМЗ-536"}]})

    engine_model: str | None = Field(default=None, min_length=2, max_length=40, description="Модель двигателя из реестра")


class Vehicle(BaseModel):
    vehicle_id: str
    garage_no: str
    make: str
    model: str | None
    vehicle_type: str
    engine_model: str
    fuel: str
    active: bool = Field(description="false — машина выведена из парка (DELETE)")
    checks_count: int
    last_check_at: str | None
    created_at: str
    updated_at: str
    manuals: list[str] = Field(description="Руководства, по которым агент отвечает для этой машины")


class VehicleSaved(Vehicle):
    created: bool = Field(description="true — машина новая, false — обновлена")


class VehicleList(BaseModel):
    items: list[Vehicle]
    total: int


def _fields(body: BaseModel) -> dict:
    fields = {k: getattr(body, k) for k in body.model_fields_set if k != "vehicle_id"}
    for k, v in list(fields.items()):
        if isinstance(v, str):
            fields[k] = v.strip()
    if fields.get("engine_model"):
        fields["engine_model"] = canonical_engine(fields["engine_model"])
    elif "engine_model" in fields:
        raise ApiError(422, "Модель двигателя не может быть пустой", field="engine_model", allowed=engines())
    return fields


@v1.get("/engines", tags=["Машины"], summary="Допустимые модели двигателей")
async def list_engines():
    """Модели двигателей, для которых в базе знаний есть руководства. Только их можно указать у машины."""
    return {"items": [{"engine_model": e, "manuals": [m.short for m in manuals_for_engine(e)]} for e in engines()]}


@v1.get("/vehicles", tags=["Машины"], summary="Список машин", response_model=VehicleList)
async def list_vehicles(include_inactive: bool = Query(default=False, description="Показать и выведенные из парка")):
    items = [_with_manuals(r) for r in fleet.repo().records(include_inactive)]
    return {"items": items, "total": len(items)}


@v1.get("/vehicles/{vehicle_id}", tags=["Машины"], summary="Карточка машины", response_model=Vehicle,
        responses={404: {"description": "Машины нет в парке"}})
async def get_vehicle(vehicle_id: str):
    return _with_manuals(vehicle_or_404(vehicle_id, include_inactive=True))


@v1.post("/vehicles", tags=["Машины"], summary="Создать или обновить машину по госномеру", response_model=VehicleSaved,
         status_code=201, responses={200: {"description": "Машина уже была: переданные поля обновлены"}})
async def save_vehicle(body: VehicleIn):
    """Учётная система парка передаёт машину. Если машина с таким госномером есть, меняются только переданные поля,
    выведенная из парка машина возвращается. Ответ 201 — машина новая, 200 — обновлена.

    Модель двигателя — только из реестра руководств (GET /api/v1/engines), иначе 422 со списком допустимых в allowed.
    """
    fields = _fields(body)
    if "engine_model" not in fields and fleet.repo().record(body.vehicle_id) is None:
        raise ApiError(422, "Для новой машины нужна модель двигателя", field="engine_model", allowed=engines())
    created = fleet.repo().upsert(body.vehicle_id, fields)
    record = _with_manuals(fleet.repo().record(body.vehicle_id))
    return JSONResponse({**record, "created": created}, status_code=201 if created else 200)


@v1.put("/vehicles/{vehicle_id}", tags=["Машины"], summary="Изменить машину", response_model=Vehicle,
        responses={404: {"description": "Машины нет в парке"}})
async def update_vehicle(vehicle_id: str, body: VehiclePatch):
    """Меняются только переданные поля. Госномер — ключ, он не меняется: для новой машины нужен POST."""
    record = vehicle_or_404(vehicle_id, include_inactive=True)
    fleet.repo().update(record["vehicle_id"], _fields(body))
    return _with_manuals(fleet.repo().record(record["vehicle_id"]))


@v1.delete("/vehicles/{vehicle_id}", tags=["Машины"], summary="Вывести машину из парка", response_model=Vehicle,
           responses={404: {"description": "Машины нет в парке"}})
async def delete_vehicle(vehicle_id: str):
    """Машина пропадает из парка и чата, история проверок, переписка и заявки сохраняются.
    Вернуть машину: POST /api/v1/vehicles с тем же госномером."""
    record = vehicle_or_404(vehicle_id, include_inactive=True)
    fleet.repo().deactivate(record["vehicle_id"])
    return _with_manuals(fleet.repo().record(record["vehicle_id"]))


# --- проверки от «НейроДВС» ---
class CheckIn(BaseModel):
    model_config = ConfigDict(extra="forbid", json_schema_extra={"examples": [
        {"vehicle_id": "A123BC77", "session_id": "S-1001", "checked_at": "2026-11-27T10:30:00+03:00"},
        {"vehicle_id": "A123BC77", "session_id": "S-1002", "checked_at": "2026-11-27T11:05:00+03:00",
         "status": "anomaly", "anomaly_type": "F02", "anomaly_title": "Повышенный стук клапанов",
         "anomaly_score": 0.71, "confidence": 0.83, "signal_quality": "good",
         "description": "Периодический стук в зоне ГРМ на холостом ходу", "model_version": "neurodvs-2.3"},
    ]})

    vehicle_id: str = Field(min_length=4, max_length=20, description="Госномер машины из парка")
    session_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9._:\-]+$",
                            description="Номер проверки в «НейроДВС»: латиница, цифры, . _ : -")
    checked_at: datetime = Field(description="Когда проверка сделана, ISO 8601. Без часового пояса — время сервера")
    status: Literal["normal", "anomaly", "check_failed"] | None = Field(
        default=None, description="Результат по желанию: если его нет, агент запросит ML-сервис")
    anomaly_type: str | None = Field(default=None, pattern=r"^F\d{2}$", description="Код неисправности F01…F14")
    anomaly_title: str | None = Field(default=None, max_length=200)
    anomaly_score: float | None = Field(default=None, ge=0, le=1)
    confidence: float | None = Field(default=None, ge=0, le=1)
    signal_quality: Literal["good", "warning", "bad"] | None = None
    description: str | None = Field(default=None, max_length=2000)
    model_version: str | None = Field(default=None, max_length=60)

    @field_validator("vehicle_id")
    @classmethod
    def _plate(cls, v: str) -> str:
        return plate(v)

    @model_validator(mode="after")
    def _result(self):
        given = [k for k in RESULT_FIELDS if getattr(self, k) is not None]
        if not given:
            return self
        if self.status is None or self.signal_quality is None:
            raise ValueError("если передан результат проверки, нужны status и signal_quality")
        if self.status == "anomaly" and not self.anomaly_type:
            raise ValueError("при status=anomaly нужен anomaly_type (код F01…F14)")
        if self.status != "anomaly" and self.anomaly_type:
            raise ValueError("anomaly_type указывается только при status=anomaly")
        return self


class CheckSaved(BaseModel):
    created: bool = Field(description="true — проверка новая, false — повтор веб-хука, данные обновлены")
    vehicle_id: str
    session_id: str
    checked_at: str
    has_result: bool = Field(description="false — результат агент запросит у ML-сервиса")
    fleet_status: str = Field(description="Статус машины в сводке парка после проверки: ok, attention, quarantine")


_tasks: set[asyncio.Task] = set()


async def _fetch_result(vehicle_id: str, session_id: str) -> None:
    """Веб-хук пришёл без результата: забираем его у ML-сервиса, чтобы сводка парка показала статус."""
    try:
        result = await clients.diagnose(vehicle_id, session_id)
    except clients.ServiceError as exc:
        log.info("Результат проверки %s %s пока не получен: %s", vehicle_id, session_id, exc)
        return
    fleet.repo().fill_result(vehicle_id, session_id, result)


@v1.post("/checks", tags=["Проверки"], summary="Проверка готова (веб-хук «НейроДВС»)", response_model=CheckSaved,
         status_code=201, responses={200: {"description": "Повтор веб-хука: проверка уже была, данные обновлены"},
                                     404: {"description": "Машины нет в парке"}})
async def receive_check(body: CheckIn):
    """«НейроДВС» сообщает, что проверка готова. Проверка сразу появляется в истории машины и в сводке парка.

    Полный результат (status, anomaly_type, … model_version) передавать не обязательно. Если он передан, агент
    использует его, когда ML-сервис эту проверку не знает. Если не передан, сервер сам запросит результат
    у ML-сервиса (POST /diagnose). Повтор веб-хука с тем же session_id безопасен: ответ 200.
    """
    vehicle_or_404(body.vehicle_id)
    when = body.checked_at if body.checked_at.tzinfo else body.checked_at.astimezone()
    checked_at = when.isoformat(timespec="seconds")
    result = None
    if body.status:
        result = {k: getattr(body, k) for k in RESULT_FIELDS}
        if body.anomaly_type and not body.anomaly_title:
            try:
                result["anomaly_title"] = fleet.fault_types().get(body.anomaly_type)
            except OSError:
                pass
        result["description"] = result["description"] or ""
        result["model_version"] = result["model_version"] or ""
    created = fleet.repo().add_check(body.vehicle_id, body.session_id, checked_at, result)
    if result is None and not (fleet.repo().check_meta(body.vehicle_id, body.session_id) or {}).get("has_result"):
        task = asyncio.create_task(_fetch_result(body.vehicle_id, body.session_id))
        _tasks.add(task)
        task.add_done_callback(_tasks.discard)
    vehicle = fleet.get_vehicle(body.vehicle_id)
    brief = fleet.brief(vehicle, [])
    meta = fleet.repo().check_meta(body.vehicle_id, body.session_id)
    out = {"created": created, "vehicle_id": body.vehicle_id, "session_id": body.session_id, "checked_at": checked_at,
           "has_result": bool(meta and meta["has_result"]), "fleet_status": brief["fleet_status"]}
    return JSONResponse(out, status_code=201 if created else 200)


# --- механики ---
class MechanicFields(BaseModel):
    model_config = ConfigDict(extra="forbid")

    age: int | None = Field(default=None, ge=16, le=90, description="Возраст", examples=[45])
    font_size: Literal["normal", "large"] | None = Field(default=None, description="Размер шрифта после входа: "
                                                          "normal — обычный, large — крупный")
    level: Literal["expert", "novice"] | None = Field(default=None, description="Подача ответов: expert — опытный, "
                                                      "коротко; novice — новичок, с пояснениями")
    pin: str | None = Field(default=None, pattern=r"^\d{4}$", description="PIN для входа, 4 цифры. Хранится только хэшем",
                            examples=["4821"])
    active: bool | None = Field(default=None, description="false — механик не работает, в списке входа его нет")


class MechanicIn(MechanicFields):
    model_config = ConfigDict(extra="forbid", json_schema_extra={"examples": [
        {"full_name": "Кузнецов Андрей Павлович", "age": 45, "font_size": "normal", "level": "expert", "pin": "4821"},
    ]})
    full_name: str = Field(min_length=2, max_length=80, description="ФИО: так механик видит себя в списке входа")
    pin: str = Field(pattern=r"^\d{4}$", description="PIN для входа, 4 цифры. Хранится только хэшем", examples=["4821"])


class MechanicPatch(MechanicFields):
    model_config = ConfigDict(extra="forbid", json_schema_extra={"examples": [{"font_size": "large", "pin": "7305"}]})
    full_name: str | None = Field(default=None, min_length=2, max_length=80)


class Mechanic(BaseModel):
    id: int
    full_name: str
    age: int | None
    font_size: Literal["normal", "large"]
    level: Literal["expert", "novice"]
    active: bool
    created_at: str
    updated_at: str


class MechanicList(BaseModel):
    items: list[Mechanic]
    total: int


def _mechanic_call(fn, *args):
    try:
        return fn(*args)
    except mechanics.MechanicError as exc:
        raise ApiError(exc.status, str(exc), **exc.extra) from exc


def _mechanic_data(body: BaseModel) -> dict:
    return {k: getattr(body, k) for k in body.model_fields_set}


def list_mechanics_data(include_inactive: bool = True) -> dict:
    items = mechanics.repo().list(include_inactive)
    return {"items": items, "total": len(items)}


@v1.get("/mechanics", tags=["Механики"], summary="Список механиков", response_model=MechanicList)
async def list_mechanics(include_inactive: bool = Query(default=True, description="Показать и не работающих")):
    return list_mechanics_data(include_inactive)


@v1.get("/mechanics/{mechanic_id}", tags=["Механики"], summary="Механик", response_model=Mechanic,
        responses={404: {"description": "Механик не найден"}})
async def get_mechanic(mechanic_id: int):
    m = mechanics.repo().get(mechanic_id)
    if m is None:
        raise ApiError(404, "Механик не найден")
    return m


@v1.post("/mechanics", tags=["Механики"], summary="Завести механика", response_model=Mechanic, status_code=201,
         responses={409: {"description": "Механик с таким ФИО уже есть"}})
async def create_mechanic(body: MechanicIn):
    """Механик появится в списке «Кто работает» и войдёт своим PIN. Размер шрифта и подача применяются после входа."""
    return _mechanic_call(mechanics.repo().create, _mechanic_data(body))


@v1.put("/mechanics/{mechanic_id}", tags=["Механики"], summary="Изменить механика", response_model=Mechanic,
        responses={404: {"description": "Механик не найден"}, 409: {"description": "Механик с таким ФИО уже есть"}})
async def update_mechanic(mechanic_id: int, body: MechanicPatch):
    """Меняются только переданные поля. Новый PIN или отключение завершают вход механика на всех устройствах."""
    return _mechanic_call(mechanics.repo().update, mechanic_id, _mechanic_data(body))


@v1.delete("/mechanics/{mechanic_id}", tags=["Механики"], summary="Отключить механика", response_model=Mechanic,
           responses={404: {"description": "Механик не найден"}})
async def delete_mechanic(mechanic_id: int):
    """Механик пропадает из списка входа. Его подписи в чате, отметки и журнал сохраняются. Вернуть: PUT с active=true."""
    return _mechanic_call(mechanics.repo().deactivate, mechanic_id)


# --- настройки подключений ---
class IntegrationsIn(BaseModel):
    model_config = ConfigDict(extra="forbid", json_schema_extra={"examples": [
        {"ml_url": "https://ml.neurodvs.example/api", "toir_url": "https://toir.example/api",
         "alert_webhook_url": "https://chat.example/hooks/abc123"},
    ]})

    ml_url: str | None = Field(default=None, max_length=500, description="Адрес ML-сервиса (POST /diagnose)")
    toir_url: str | None = Field(default=None, max_length=500, description="Адрес ТОиР (POST /tickets)")
    alert_webhook_url: str | None = Field(default=None, max_length=500,
                                          description="Куда сообщать администратору о вопросах без ответа")
    ml_token: str | None = Field(default=None, max_length=500, description="Токен ML-сервиса: Authorization: Bearer")
    toir_token: str | None = Field(default=None, max_length=500, description="Токен ТОиР: Authorization: Bearer")
    llm_mode: Literal["cloud", "yandex", "local", ""] | None = Field(
        default=None, description="Модель: cloud — облако из настроек сервера (ключ встроен), yandex — Yandex AI Studio, "
                                  "local — сервер с форматом OpenAI в контуре заказчика (Ollama, vLLM)")
    llm_local_url: str | None = Field(default=None, max_length=500, description="Адрес локальной модели, например http://сервер:11434/v1")
    llm_local_model: str | None = Field(default=None, max_length=200, description="Имя модели на локальном сервере")
    llm_local_key: str | None = Field(default=None, max_length=500, description="Ключ локального сервера, если нужен")
    yandex_folder: str | None = Field(default=None, max_length=100, description="Идентификатор каталога Yandex Cloud")
    yandex_key: str | None = Field(default=None, max_length=500, description="API-ключ Yandex AI Studio")
    yandex_model: str | None = Field(default=None, max_length=200, description="Модель, например yandexgpt/latest")


def integrations_data() -> dict:
    keys = auth.api_keys()
    return {**integrations.current(), "api": {"enabled": bool(keys), "keys": len(keys), "docs_url": "/api/docs"},
            "demo": demo.enabled()}


def save_integrations(body: IntegrationsIn) -> dict:
    try:
        changed = integrations.update({k: getattr(body, k) for k in body.model_fields_set})
    except integrations.SettingsError as exc:
        raise ApiError(422, str(exc), field=exc.field) from exc
    return {**integrations_data(), "changed": changed}


@v1.get("/settings/integrations", tags=["Настройки"], summary="Настройки подключений")
async def get_integrations():
    """Действующие адреса и токены. Секреты скрыты: токены — кроме последних 4 знаков, у веб-хука — путь,
    у адресов — пароль и значения параметров. source: db — задано здесь, env — из .env."""
    return integrations_data()


@v1.put("/settings/integrations", tags=["Настройки"], summary="Изменить настройки подключений")
async def put_integrations(body: IntegrationsIn):
    """Значения хранятся в базе и перекрывают .env, действуют сразу. Поле не передано или null — без изменений,
    пустая строка — вернуть значение из .env. Скрытое значение из GET (с •••) не сохраняется."""
    return save_integrations(body)


# --- коннектор к агенту ---
class AgentDiagnoseIn(BaseModel):
    model_config = ConfigDict(extra="forbid", json_schema_extra={"examples": [{"vehicle_id": "A101TT77", "session_id": "S-9003"}]})
    vehicle_id: str = Field(min_length=4, max_length=20)
    session_id: str | None = Field(default=None, max_length=64, description="Проверка. Не указана — последняя")
    mechanic: str | None = Field(default=None, max_length=60, description="ФИО механика: автор запроса в журнале")
    level: Literal["expert", "novice"] = "expert"


class AgentAskIn(BaseModel):
    model_config = ConfigDict(extra="forbid", json_schema_extra={"examples": [
        {"vehicle_id": "A101TT77", "text": "Какое давление масла должно быть на прогретом двигателе?", "mechanic": "Иванов Иван"},
        {"vehicle_id": "A101TT77", "session_id": "S-9003", "text": "Создай заявку на дефектовку"},
    ]})
    vehicle_id: str = Field(min_length=4, max_length=20)
    session_id: str | None = Field(default=None, max_length=64, description="Проверка. Не указана — последняя")
    text: str = Field(min_length=1, max_length=2000, description="Вопрос или команда механика")
    mechanic: str | None = Field(default=None, max_length=60, description="ФИО механика: автор вопроса в журнале")
    level: Literal["expert", "novice"] = Field(default="expert", description="Подача ответа")


class AgentConfirmIn(BaseModel):
    model_config = ConfigDict(extra="forbid", json_schema_extra={"examples": [{"draft_id": "d_12", "mechanic": "Иванов Иван"}]})
    draft_id: str = Field(pattern=r"^d_\d+$", description="Черновик из ответа kind=ticket_draft")
    warning_ack: bool = Field(default=False, description="Механик понимает, что запись с помехами (requires_warning_ack)")
    mechanic: str | None = Field(default=None, max_length=60)
    level: Literal["expert", "novice"] = "expert"


class AgentResult(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [{
        "message_id": "m_42", "vehicle_id": "A101TT77", "session_id": "S-9003", "kind": "answer",
        "text": "Давление масла прогретого двигателя должно быть не менее 400 кПа.",
        "answer": {"summary": "…", "checks": [{"text": "Проверить давление масла контрольным манометром",
                                               "refs": [{"manual_id": "yamz236_rk", "short": "РК ЯМЗ-236М2",
                                                         "pdf_page": 10, "quote": "…"}]}],
                   "repair": [], "not_found": False},
        "diagnosis": None, "assessment": None, "draft": None, "ticket": None,
    }]})

    message_id: str = Field(description="Ответ агента в переписке по машине")
    vehicle_id: str
    session_id: str | None
    kind: Literal["verdict", "answer", "ticket_draft", "ticket_created", "notice"] = Field(
        description="verdict — разбор проверки; answer — ответ по руководству; ticket_draft — черновик заявки, "
                    "ждёт подтверждения (POST /api/v1/agent/confirm); ticket_created — заявка в ТОиР; notice — сообщение")
    text: str = Field(description="Главная фраза ответа")
    diagnosis: dict | None = Field(default=None, description="Результат проверки от ML-сервиса (для verdict)")
    assessment: dict | None = Field(default=None, description="Оценка правилами: исход, приоритет с основанием, "
                                                              "можно ли оформить заявку")
    answer: dict | None = Field(default=None, description="Пункты ответа: checks и repair со ссылками refs "
                                                          "(документ, страница PDF, дословная цитата)")
    draft: dict | None = Field(default=None, description="Черновик заявки: работы, запчасти, источники, приоритет")
    ticket: dict | None = Field(default=None, description="Созданная заявка с номером ticket_id")
    steps: list[dict] = Field(default_factory=list, description="Шаги агента: инструменты и их итог")
    usage: dict = Field(default_factory=dict, description="Токены, стоимость и время ответа")


def _runtime() -> dict:
    from .main import state  # main подключает этот модуль: импорт при вызове, не при загрузке

    return state


async def run_agent(vehicle: dict, **kwargs) -> dict:
    """Ход агента синхронно: тот же run_turn, что у чата, ответ — когда агент закончил."""
    rt = _runtime()
    vehicle_id = vehicle["vehicle_id"]

    async def work(emit: turns.Emit) -> None:
        await run_turn(vehicle=vehicle, store=rt["store"], index=rt["index"], settings=get_settings(),
                       llm=rt["llm"], emit=emit, **kwargs)

    turn = turns.start(vehicle_id, work)
    if turn is None:
        raise ApiError(409, "Агент ещё отвечает на предыдущий запрос по этой машине. Повторите, когда он закончит.")
    message, error = None, None
    async for event in turn.follow():
        if event.get("type") == "message":
            message = event["message"]
        elif event.get("type") == "error":
            error = event.get("text")
    if message is None:
        turns.seen(vehicle_id)  # ошибку получил вызвавший, механику в чате о ней не напоминаем
        raise ApiError(502, error or "Агент не дал ответа. Повторите запрос.")
    return {
        "message_id": message["id"], "vehicle_id": vehicle_id, "session_id": message.get("session_id"),
        "kind": message.get("kind"), "text": message.get("text", ""),
        **{k: message.get(k) for k in ("diagnosis", "assessment", "answer", "draft", "ticket")},
        "steps": message.get("steps", []), "usage": message.get("usage", {}),
    }


def _agent_vehicle(vehicle_id: str, session_id: str | None) -> tuple[dict, str]:
    vid = vehicle_or_404(vehicle_id)["vehicle_id"]
    vehicle = fleet.get_vehicle(vid)
    sid = session_id or (vehicle["sessions"][-1]["session_id"] if vehicle["sessions"] else "")
    if not sid:
        raise ApiError(404, f"У машины {vid} ещё нет проверок. Передайте проверку: POST /api/v1/checks.")
    if fleet.get_session(vehicle, sid) is None:
        raise ApiError(404, f"У машины {vid} нет проверки {sid}")
    return vehicle, sid


def _profile(mechanic: str | None, level: str) -> dict:
    name = (mechanic or "").strip()
    return {"level": level, **({"name": name} if name else {})}


AGENT_ERRORS = {404: {"description": "Нет машины или проверки"},
                409: {"description": "По машине уже идёт ход агента"},
                502: {"description": "Сбой модели или внешнего сервиса: текст в detail"}}


@v1.post("/agent/diagnose", tags=["Агент"], summary="Разбор результата проверки", response_model=AgentResult,
         responses=AGENT_ERRORS)
async def agent_diagnose(body: AgentDiagnoseIn):
    """Агент получает результат проверки, оценивает его правилами и объясняет: исход, приоритет, что проверить
    по руководству (со страницами). То же, что кнопка «Получить результат диагностики» в чате.
    Ответ приходит, когда агент закончил: обычно 10–60 секунд. Ход пишется в переписку по машине и в журнал."""
    vehicle, sid = _agent_vehicle(body.vehicle_id, body.session_id)
    return await run_agent(vehicle, session_id=sid, text="Получи результат диагностики", photos=[],
                           profile=_profile(body.mechanic, body.level))


@v1.post("/agent/ask", tags=["Агент"], summary="Вопрос агенту", response_model=AgentResult, responses=AGENT_ERRORS)
async def agent_ask(body: AgentAskIn):
    """Вопрос механика по машине. Агент отвечает строго по руководствам двигателя этой машины со ссылкой на страницу.
    Команда «Создай заявку на дефектовку» вернёт черновик (kind=ticket_draft): отправка в ТОиР — только после
    подтверждения механиком (POST /api/v1/agent/confirm)."""
    vehicle, sid = _agent_vehicle(body.vehicle_id, body.session_id)
    return await run_agent(vehicle, session_id=sid, text=body.text.strip(), photos=[],
                           profile=_profile(body.mechanic, body.level))


@v1.post("/agent/confirm", tags=["Агент"], summary="Подтвердить черновик заявки", response_model=AgentResult,
         responses={**AGENT_ERRORS, 400: {"description": "Нужно согласие с предупреждением о помехах"}})
async def agent_confirm(body: AgentConfirmIn):
    """Механик подтвердил черновик: агент отправляет заявку в ТОиР. Ответ kind=ticket_created с номером заявки
    или kind=notice с причиной отказа."""
    store = _runtime()["store"]
    draft = store.draft(body.draft_id)
    if draft is None:
        raise ApiError(404, "Черновик не найден")
    if draft["status"] == "sent":
        raise ApiError(409, f"Заявка уже отправлена: {draft['ticket_id']}")
    if draft["requires_warning_ack"] and not body.warning_ack:
        raise ApiError(400, "Запись с помехами: передайте warning_ack=true, если механик понимает предварительный "
                            "характер вывода")
    vehicle = fleet.get_vehicle(draft["vehicle_id"])
    if vehicle is None:
        raise ApiError(404, f"Машины {draft['vehicle_id']} нет в парке")
    return await run_agent(vehicle, session_id=draft["session_id"],
                           text=f"Подтверждаю заявку {body.draft_id}. Отправь её в ТОиР.",
                           confirmed_draft_id=body.draft_id, warning_ack=body.warning_ack,
                           profile=_profile(body.mechanic, body.level))


# --- экраны администратора (вход по куке, см. auth.ADMIN_PREFIXES) ---
@admin.get("/mechanics")
async def admin_mechanics():
    return list_mechanics_data(True)


@admin.post("/mechanics", status_code=201)
async def admin_create_mechanic(body: MechanicIn):
    return _mechanic_call(mechanics.repo().create, _mechanic_data(body))


def _demo_mechanic_guard(mechanic_id: int, what: str) -> None:
    """Демо-механики (их PIN видны на экране входа) на демо-стенде не меняются: иначе вход сломается у всех."""
    if demo.enabled() and mechanic_id in mechanics.repo().demo_pins():
        raise ApiError(403, demo.locked(what), demo_locked=True)


@admin.put("/mechanics/{mechanic_id}")
async def admin_update_mechanic(mechanic_id: int, body: MechanicPatch):
    _demo_mechanic_guard(mechanic_id, "менять демо-механиков")
    return _mechanic_call(mechanics.repo().update, mechanic_id, _mechanic_data(body))


@admin.delete("/mechanics/{mechanic_id}")
async def admin_delete_mechanic(mechanic_id: int):
    _demo_mechanic_guard(mechanic_id, "удалять демо-механиков")
    _mechanic_call(mechanics.repo().delete, mechanic_id)
    return {"deleted": True}


@admin.get("/integrations")
async def admin_integrations():
    return {**integrations_data(), "health": await clients.health()}


@admin.put("/integrations")
async def admin_save_integrations(body: IntegrationsIn):
    if demo.enabled():
        raise ApiError(403, demo.locked("менять подключения и модель"), demo_locked=True)
    return {**save_integrations(body), "health": await clients.health()}


# --- подключение к приложению ---
DOC = """
Подключение внешних систем к «Цифровому механику»: они передают нам данные, агент отвечает по ним.

### Кто и что передаёт

| Система | Что передаёт | Методы |
|---|---|---|
| Учётная система парка | машины парка | `GET` `POST` `/vehicles`, `PUT` `DELETE` `/vehicles/{vehicle_id}` |
| «НейроДВС» | «проверка готова» и её результат | `POST /checks` |
| Кадровая система | механики: ФИО, PIN, шрифт, подача | `GET` `POST` `/mechanics`, `PUT` `DELETE` `/mechanics/{id}` |
| Любая система | разбор проверки и вопрос агенту | `POST /agent/diagnose`, `POST /agent/ask`, `POST /agent/confirm` |

Обратное направление — к вашим сервисам — сервер ведёт сам: берёт результат проверки у ML-сервиса и отправляет
подтверждённую заявку в ТОиР. Адреса и ключи задаются на экране «Подключения» или в `GET`/`PUT /settings/integrations`.
Для ТОиР на 1С подготовлена заготовка переходника.

### Доступ

Каждый запрос — с заголовком `X-API-Key: <ключ>`. Ключи задаёт администратор сервера в `INTEGRATION_API_KEYS`,
по ключу на систему. Пока ключей нет, API выключен.

### Ответы с ошибкой

Всегда JSON, текст для человека — в поле `detail`.

| Код | Когда |
|---|---|
| `401` | нет ключа |
| `403` | ключ не подходит |
| `404` | нет машины, проверки или механика |
| `409` | конфликт: агент ещё отвечает по машине, такое ФИО уже есть, заявка уже отправлена |
| `422` | поля не прошли проверку: по полям — в `errors`, допустимые модели двигателя — в `allowed` |
| `502` | сбой модели или внешнего сервиса |
| `503` | API выключен |

Примеры запросов на каждый метод и заготовка переходника под 1С — в `docs/integration.md` репозитория.
"""
TAGS = [
    {"name": "Машины", "description": "Парк из учётной системы. Госномер — ключ машины."},
    {"name": "Проверки", "description": "Веб-хук «НейроДВС»: проверка готова."},
    {"name": "Агент", "description": "Коннектор к агенту: тот же ход, что в чате, ответ одним JSON."},
    {"name": "Механики", "description": "Кто входит в систему: ФИО, PIN, размер шрифта и подача."},
    {"name": "Настройки", "description": "Адреса и токены ML-сервиса, ТОиР и веб-хука администратора."},
]


def install(app: FastAPI) -> None:
    """Подключает /api/v1 и маршруты экранов администратора, понятные ошибки и документацию только по /api/v1."""
    app.include_router(v1)
    app.include_router(admin)
    app.add_exception_handler(ApiError, _api_error)
    app.add_exception_handler(RequestValidationError, _validation_error)

    def openapi() -> dict[str, Any]:
        if app.openapi_schema is None:
            schema = get_openapi(title="Цифровой механик: API для внешних систем", version=VERSION,
                                 description=DOC, routes=v1.routes, tags=TAGS)
            for path in schema.get("paths", {}).values():
                for operation in path.values():
                    for response in operation.get("responses", {}).values():
                        if response.get("description") == "Successful Response":
                            response["description"] = "Готово"
            app.openapi_schema = schema
        return app.openapi_schema

    app.openapi = openapi
