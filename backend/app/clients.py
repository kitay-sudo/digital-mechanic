"""Клиенты внешних сервисов: ML-диагностика и приёмник заявок (ТОиР).

Работают строго по контракту раздела 5 ТЗ. Адреса берутся из переменных окружения или из
настроек подключений, которые администратор задал в интерфейсе (integrations.py), поэтому
заглушки заменяются рабочими сервисами без правки кода (F6).

Заявку принимает «приёмник заявок» (TicketSink). Сейчас это HTTP-сервис ТОиР по контракту ТЗ.
Под другую учётную систему (например, 1С:ТОиР) пишется один переходник с методами create и health,
он подключается переменной TICKET_SINK=модуль:Класс. Пример заготовки: docs/integration.md.
"""
from __future__ import annotations

import importlib
from functools import lru_cache
from typing import Protocol, runtime_checkable

import httpx

from .config import Settings, get_settings


class ServiceError(Exception):
    """Ошибка внешнего сервиса с текстом, который можно показать механику."""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"} if token else {}


async def diagnose(vehicle_id: str, session_id: str) -> dict:
    s = get_settings()
    url = f"{s.ml_url}/diagnose"
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(url, json={"vehicle_id": vehicle_id, "session_id": session_id},
                                     headers=_auth(s.ml_token))
    except httpx.HTTPError as exc:
        raise ServiceError(f"Нет связи с ML-сервисом диагностики ({url}): {exc.__class__.__name__}") from exc
    if resp.status_code == 404:
        raise ServiceError(f"ML-сервис не знает проверку {session_id} машины {vehicle_id}", 404)
    if resp.status_code in (400, 422):
        raise ServiceError("ML-сервис не принял запрос: он собран не по схеме", resp.status_code)
    if resp.status_code != 200:
        raise ServiceError(f"ML-сервис ответил кодом {resp.status_code}", resp.status_code)
    return resp.json()


# --- приёмник заявок ---
@runtime_checkable
class TicketSink(Protocol):
    """Куда уходит подтверждённая механиком заявка на дефектовку.

    create(payload) получает заявку строго по контракту раздела 5 ТЗ:
        {"vehicle_id", "session_id", "anomaly_type", "conclusion", "urgency": "low|medium|high",
         "operations": [str], "spare_parts": [str], "references": [{"manual", "pdf_page"}]}
    и возвращает {"ticket_id": str, "status": str} — номер заявки в учётной системе.
    Если система заявку не приняла, create бросает ServiceError с текстом для механика
    (status — код ответа системы, если он есть). Повторять отправку агент не будет:
    механик увидит причину и решит сам.

    health() — доступна ли система; нужен для /api/health и экрана подключений.
    """

    name: str

    async def create(self, payload: dict) -> dict: ...

    async def health(self) -> bool: ...


class ToirHttpSink:
    """ТОиР по HTTP: POST {toir_url}/tickets, ответ 201 с ticket_id (контракт ТЗ и заглушки mock-toir)."""

    name = "toir"

    def __init__(self, settings: Settings):
        self.url = settings.toir_url
        self.token = settings.toir_token

    async def create(self, payload: dict) -> dict:
        url = f"{self.url}/tickets"
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(url, json=payload, headers=_auth(self.token))
        except httpx.HTTPError as exc:
            raise ServiceError(f"Нет связи с системой ТОиР ({url}): {exc.__class__.__name__}") from exc
        if resp.status_code == 404:
            raise ServiceError("ТОиР не знает такую машину или проверку", 404)
        if resp.status_code in (400, 418, 422):
            raise ServiceError(f"ТОиР не приняла заявку: она собрана не по схеме ({resp.text[:300]})", resp.status_code)
        if resp.status_code != 201:
            raise ServiceError(f"ТОиР ответила кодом {resp.status_code}", resp.status_code)
        return resp.json()

    async def health(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=3) as client:
                return (await client.get(f"{self.url}/health", headers=_auth(self.token))).status_code == 200
        except httpx.HTTPError:
            return False


@lru_cache
def _sink_class(spec: str) -> type:
    """TICKET_SINK: «toir» (по умолчанию) или «пакет.модуль:Класс» своего переходника."""
    if spec in ("", "toir"):
        return ToirHttpSink
    module, _, name = spec.partition(":")
    if not name:
        raise ServiceError(f"TICKET_SINK задан неверно: «{spec}». Нужно «модуль:Класс» или «toir».")
    return getattr(importlib.import_module(module), name)


def ticket_sink() -> TicketSink:
    """Приёмник заявок с текущими настройками: адрес и токен могут смениться без перезапуска."""
    settings = get_settings()
    return _sink_class(settings.ticket_sink)(settings)


async def create_ticket(payload: dict) -> dict:
    return await ticket_sink().create(payload)


async def health() -> dict:
    s = get_settings()
    out = {}
    async with httpx.AsyncClient(timeout=3) as client:
        try:
            out["ml"] = (await client.get(f"{s.ml_url}/health", headers=_auth(s.ml_token))).status_code == 200
        except httpx.HTTPError:
            out["ml"] = False
    try:
        out["toir"] = await ticket_sink().health()
    except Exception:  # чужой переходник не должен ронять проверку здоровья
        out["toir"] = False
    return out
