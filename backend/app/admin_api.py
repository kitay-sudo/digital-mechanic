"""Эндпоинты администратора и главного механика: журнал обращений, разбор случаев.

Подключаются в main.py одной строкой (include_router). Хранилище берётся из состояния сервера.
"""
from __future__ import annotations

import re
from datetime import date

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from . import alerts, digest, journal
from .config import get_settings
from .store import Store

router = APIRouter()


def store() -> Store:
    from .main import state  # main подключает этот модуль, поэтому состояние берём при запросе

    return state["store"]


def _period(start: str | None, end: str | None, default_today: bool = False):
    try:
        return journal.period(start, end, default_today)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


def _filters(start: str | None, end: str | None, vehicle_id: str | None, mechanic: str | None,
             kind: str | None, q: str | None) -> dict:
    lo, hi = _period(start, end)
    if kind and kind not in journal.TYPES:
        raise HTTPException(400, f"Неизвестный тип случая: {kind}")
    return {"from_ts": lo.timestamp() if lo else None, "to_ts": hi.timestamp() if hi else None,
            "vehicle_id": (vehicle_id or "").strip() or None, "mechanic": (mechanic or "").strip() or None,
            "type": kind or None, "q": q}


# --- журнал обращений ---
@router.get("/api/audit")
async def audit(
    page: int = Query(default=1, ge=1),
    page_size: int | None = Query(default=None, ge=1, le=journal.MAX_PAGE_SIZE),
    limit: int | None = Query(default=None, ge=1, le=500, description="Старый параметр: размер первой страницы"),
    start: str | None = Query(default=None, alias="from", max_length=40),
    end: str | None = Query(default=None, alias="to", max_length=40),
    vehicle_id: str | None = Query(default=None, max_length=40),
    mechanic: str | None = Query(default=None, max_length=60),
    kind: str | None = Query(default=None, alias="type", max_length=20),
    status: str = Query(default="all", pattern="^(all|open|new|in_work|reviewed|cases)$"),
    q: str | None = Query(default=None, max_length=200),
):
    """Весь журнал постранично: кто что спросил, что ответил агент, на какие источники сослался.

    Строка — группа повторов (repeats), у случаев есть статус разбора (status). Новые сверху.
    """
    size = page_size or min(limit or 20, journal.MAX_PAGE_SIZE)
    filters = _filters(start, end, vehicle_id, mechanic, kind, q)
    data = journal.page(store(), filters, status, page, size)
    return {**data, "gaps_open": journal.open_count(store()), "facets": journal.facets(store())}


@router.get("/api/audit/gaps")
async def audit_gaps():
    """Сколько случаев «новый» и «в работе»: число у пункта «Журнал»."""
    return {"open": journal.open_count(store())}


@router.get("/api/audit/digest")
async def audit_digest(day: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")):
    """Текст сводки администратору за день (по умолчанию сегодня), как он уйдёт на ALERT_WEBHOOK_URL."""
    try:
        when = date.fromisoformat(day) if day else None
    except ValueError as exc:
        raise HTTPException(400, f"Неверная дата: {day}") from exc
    summary = digest.build(store(), when)
    return {**summary, "mode": alerts.alert_mode(), "time": digest.digest_time().strftime("%H:%M"),
            "sent_at": digest.sent_at(store(), date.fromisoformat(summary["day"])),
            "webhook": bool(get_settings().alert_webhook_url)}


def _item_id(item_id: str) -> str:
    if not re.fullmatch(r"[ma]_\d+", item_id):
        raise HTTPException(404, "Обращение не найдено")
    return item_id


@router.get("/api/audit/{item_id}")
async def audit_case(item_id: str):
    """Карточка случая: вопрос, ответ агента, источники, сообщения механика, повторы, история статуса."""
    item = journal.case(store(), _item_id(item_id))
    if item is None:
        raise HTTPException(404, "Обращение не найдено")
    return item


class StatusRequest(BaseModel):
    ids: list[str] = Field(min_length=1, max_length=200)
    status: str = Field(pattern="^(new|in_work|reviewed)$")
    comment: str | None = Field(default=None, max_length=2000)
    # Кто разобрал. Пока имя приходит из интерфейса, позже его даст вход администратора
    reviewer: str | None = Field(default=None, max_length=60)


@router.post("/api/audit/status")
async def audit_status(req: StatusRequest):
    """Статус разбора у нескольких строк сразу. Отмечается вся группа повторов каждой строки."""
    ids = [_item_id(i) for i in req.ids]
    result = journal.set_status(store(), ids, req.status, req.comment, req.reviewer)
    if not result["updated"]:
        raise HTTPException(404, "Обращения не найдены")
    return {**result, "gaps_open": journal.open_count(store())}


class ReviewRequest(BaseModel):
    reviewed: bool = True


@router.post("/api/audit/{item_id}/review")
async def review_gap(item_id: str, req: ReviewRequest):
    """Старая отметка «Разобрано»: статус «разобрано» или возврат в «новый»."""
    if journal.case(store(), _item_id(item_id)) is None:
        raise HTTPException(404, "Обращение не найдено")
    result = journal.set_status(store(), [item_id], "reviewed" if req.reviewed else "new")
    return {"id": item_id, "reviewed_at": result["at"] if req.reviewed else None}
