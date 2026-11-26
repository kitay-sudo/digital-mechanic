"""Клиенты внешних сервисов: ML-диагностика и ТОиР.

Работают строго по контракту раздела 5 ТЗ. Адреса берутся из переменных окружения,
поэтому заглушки заменяются рабочими сервисами без правки кода (F6).
"""
from __future__ import annotations

import httpx

from .config import get_settings


class ServiceError(Exception):
    """Ошибка внешнего сервиса с текстом, который можно показать механику."""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


async def diagnose(vehicle_id: str, session_id: str) -> dict:
    url = f"{get_settings().ml_url}/diagnose"
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(url, json={"vehicle_id": vehicle_id, "session_id": session_id})
    except httpx.HTTPError as exc:
        raise ServiceError(f"Нет связи с ML-сервисом диагностики ({url}): {exc.__class__.__name__}") from exc
    if resp.status_code == 404:
        raise ServiceError(f"ML-сервис не знает проверку {session_id} машины {vehicle_id}", 404)
    if resp.status_code in (400, 422):
        raise ServiceError("ML-сервис не принял запрос: он собран не по схеме", resp.status_code)
    if resp.status_code != 200:
        raise ServiceError(f"ML-сервис ответил кодом {resp.status_code}", resp.status_code)
    return resp.json()


async def create_ticket(payload: dict) -> dict:
    url = f"{get_settings().toir_url}/tickets"
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(url, json=payload)
    except httpx.HTTPError as exc:
        raise ServiceError(f"Нет связи с системой ТОиР ({url}): {exc.__class__.__name__}") from exc
    if resp.status_code == 404:
        raise ServiceError("ТОиР не знает такую машину или проверку", 404)
    if resp.status_code in (400, 418, 422):
        raise ServiceError(f"ТОиР не приняла заявку: она собрана не по схеме ({resp.text[:300]})", resp.status_code)
    if resp.status_code != 201:
        raise ServiceError(f"ТОиР ответила кодом {resp.status_code}", resp.status_code)
    return resp.json()


async def health() -> dict:
    s = get_settings()
    out = {}
    async with httpx.AsyncClient(timeout=3) as client:
        for name, base in (("ml", s.ml_url), ("toir", s.toir_url)):
            try:
                out[name] = (await client.get(f"{base}/health")).status_code == 200
            except httpx.HTTPError:
                out[name] = False
    return out
