"""Эндпоинты администратора и главного механика: журнал обращений, разбор случаев.

Подключаются в main.py одной строкой (include_router). Хранилище берётся из состояния сервера.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timezone

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from . import alerts, auth, digest, fleet, journal, shift
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
    # Кто разобрал: внешняя система по ключу API передаёт имя сама, при входе администратора подпись ставит сервер
    reviewer: str | None = Field(default=None, max_length=60)


ADMIN_SIGNATURE = "Администратор"


def reviewer_of(request: Request, given: str | None) -> str | None:
    """Решение администратора подписывает его вход, а не фамилия, оставшаяся в браузере от механика."""
    session = auth.session_from_cookie(request.headers.get("cookie"))
    if session and session.get("role") == "admin":
        return ADMIN_SIGNATURE
    return (given or "").strip() or None


@router.post("/api/audit/status")
async def audit_status(req: StatusRequest, request: Request):
    """Статус разбора у нескольких строк сразу. Отмечается вся группа повторов каждой строки."""
    ids = [_item_id(i) for i in req.ids]
    result = journal.set_status(store(), ids, req.status, req.comment, reviewer_of(request, req.reviewer))
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


# --- вопрос механика администратору напрямую ---
class AdminMessageRequest(BaseModel):
    vehicle_id: str | None = Field(default=None, max_length=40)
    text: str = Field(min_length=1, max_length=1000)
    author: str | None = Field(default=None, max_length=60)


@router.post("/api/admin-messages")
async def admin_message(req: AdminMessageRequest):
    """Механик пишет администратору не по ответу агента: случай «От механика» в журнале, без ответа агента."""
    text = req.text.strip()
    if not text:
        raise HTTPException(400, "Пустое сообщение: напишите, что случилось")
    vehicle_id = (req.vehicle_id or "").strip() or None
    vehicle = fleet.get_vehicle(vehicle_id) if vehicle_id else None
    if vehicle_id and vehicle is None:
        raise HTTPException(404, f"Машины {vehicle_id} нет в парке")
    author = (req.author or "").strip() or None
    saved = journal.add_admin_message(store(), vehicle_id, text, author)
    url = get_settings().alert_webhook_url
    if url and alerts.sends_now("report"):
        head = f"Механик{' ' + author if author else ''} написал администратору."
        if vehicle:
            head += (f" Машина {vehicle.get('model') or vehicle_id}, госномер {vehicle_id}, "
                     f"двигатель {vehicle.get('engine_model', '—')}.")
        alerts.send(url, {"text": f"{head}\nСообщение: {text}", "type": "report", "vehicle_id": vehicle_id,
                          "author": author, "question": text, "created_at": saved["created_at"]})
    return saved


# --- сводка смены и метрики пилота: период с/по, по умолчанию сегодня ---
@router.get("/api/shift-summary")
async def shift_summary(start: str | None = Query(default=None, alias="from", max_length=40),
                        end: str | None = Query(default=None, alias="to", max_length=40)):
    """Кто работал, сколько вопросов, какие шаги отмечены и кем, какие заявки созданы, сколько случаев ждут разбора."""
    lo, hi = _period(start, end, default_today=True)
    return shift.summary(store(), lo or datetime.fromtimestamp(0, timezone.utc), hi or datetime.now(timezone.utc))


@router.get("/api/metrics")
async def pilot_metrics(start: str | None = Query(default=None, alias="from", max_length=40),
                        end: str | None = Query(default=None, alias="to", max_length=40)):
    """Метрики пилота: от вердикта до заявки, честные отказы, повтор после ремонта, время ответа и стоимость."""
    lo, hi = _period(start, end, default_today=True)
    return shift.metrics(store(), lo or datetime.fromtimestamp(0, timezone.utc), hi or datetime.now(timezone.utc))
