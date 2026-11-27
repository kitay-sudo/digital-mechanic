"""HTTP-сервер «Цифрового механика». Контракт описан в docs/api.md."""
from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field

from . import clients, fleet, rules, turns
from .agent import prompt
from .agent.llm import build_llm
from .agent.loop import run_turn
from .config import get_settings
from .kb import render
from .kb.index import get_index
from .manuals import manual_by_id
from .store import Store

log = logging.getLogger("mechanic")
state: dict = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    state["store"] = Store(settings.db_path)
    state["index"] = get_index()
    state["llm"] = build_llm()
    stats = state["index"].stats()
    if not stats["chunks"]:
        log.warning("База знаний пуста (%s). Задайте MATERIALS_URL и выполните: python -m app.materials", settings.pdf_dir)
    yield
    await turns.shutdown()


app = FastAPI(title="Цифровой механик", version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


def store() -> Store:
    return state["store"]


def vehicle_or_404(vehicle_id: str) -> dict:
    vehicle = fleet.get_vehicle(vehicle_id)
    if vehicle is None:
        raise HTTPException(404, f"Машины {vehicle_id} нет в парке")
    return vehicle


# --- справочные запросы ---
@app.get("/api/health")
async def health():
    return {"status": "ok", **(await clients.health()), "kb": state["index"].stats(),
            "llm": {"provider": state["llm"].name, "model": state["llm"].model}}


def kb_status() -> dict:
    """Какие руководства проиндексированы. Пустая база — ошибка настройки, интерфейс предупреждает о ней."""
    from .manuals import all_manuals

    index = state["index"]
    missing = [m.short for m in all_manuals() if index.page_count(m.id) == 0]
    return {"ready": not missing, "missing": missing, "pages": index.stats()["pages"]}


@app.get("/api/config")
async def config():
    settings = get_settings()
    llm = state["llm"]
    return {
        "llm": {"provider": llm.name, "model": llm.model, "mock": llm.is_mock},
        "kb": kb_status(),
        "thresholds": {"confidence_min": settings.confidence_min},
        "priority_actions": rules.ACTIONS,
        "levels": prompt.LEVEL_LABELS,
    }


@app.get("/api/fleet")
async def get_fleet():
    return fleet.fleet(store().tickets_by_vehicle())


@app.get("/api/vehicles/{vehicle_id}")
async def get_vehicle(vehicle_id: str):
    return fleet.detail(vehicle_or_404(vehicle_id), store().tickets(vehicle_id))


# --- чат ---
class Profile(BaseModel):
    """Настройки механика: язык ответов и уровень подачи."""
    level: str = Field(default="expert", pattern="^(expert|novice)$")


class ChatRequest(BaseModel):
    vehicle_id: str = Field(min_length=1)
    session_id: str | None = None
    text: str = Field(min_length=1, max_length=2000)
    profile: Profile | None = None


class ConfirmRequest(BaseModel):
    warning_ack: bool = False
    profile: Profile | None = None


class DraftPatch(BaseModel):
    conclusion: str | None = Field(default=None, min_length=1, max_length=1000)
    urgency: str | None = Field(default=None, pattern="^(low|medium|high)$")


def ndjson(turn: turns.Turn) -> StreamingResponse:
    """События хода построчно (NDJSON), с начала хода и до конца. Обрыв соединения ход не останавливает."""
    async def lines():
        async for event in turn.follow():
            yield json.dumps(event, ensure_ascii=False) + "\n"

    return StreamingResponse(lines(), media_type="application/x-ndjson",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def stream_turn(vehicle: dict, **kwargs) -> StreamingResponse:
    """Запускает ход агента в фоне и отдаёт его события. По одной машине идёт один ход."""
    vehicle_id = vehicle["vehicle_id"]

    async def work(emit: turns.Emit) -> None:
        await run_turn(vehicle=vehicle, store=store(), index=state["index"], settings=get_settings(),
                       llm=state["llm"], emit=emit, **kwargs)

    turn = turns.start(vehicle_id, work)
    if turn is None:
        raise HTTPException(409, "Агент ещё отвечает на предыдущий запрос по этой машине. Дождитесь ответа.")
    return ndjson(turn)


@app.post("/api/chat")
async def chat(req: ChatRequest):
    vehicle = vehicle_or_404(req.vehicle_id)
    session_id = req.session_id or (vehicle["sessions"][-1]["session_id"] if vehicle["sessions"] else "")
    if fleet.get_session(vehicle, session_id) is None:
        raise HTTPException(404, f"У машины {req.vehicle_id} нет проверки {session_id}")
    return stream_turn(vehicle, session_id=session_id, text=req.text.strip(),
                       profile=req.profile.model_dump() if req.profile else None)


@app.get("/api/conversations/{vehicle_id}")
async def conversation(vehicle_id: str):
    vehicle_or_404(vehicle_id)
    return {"messages": store().messages(vehicle_id), "turn": turns.status(vehicle_id)}


@app.get("/api/conversations/{vehicle_id}/turn")
async def follow_turn(vehicle_id: str):
    """События хода, начатого раньше: с начала и до конца. Пустой ответ, если хода нет."""
    vehicle_or_404(vehicle_id)
    return ndjson(turns.get(vehicle_id) or turns.Turn.empty())


@app.delete("/api/conversations/{vehicle_id}/turn")
async def seen_turn(vehicle_id: str):
    """Страница показала механику ошибку хода: больше о ней не напоминаем."""
    vehicle_or_404(vehicle_id)
    turns.seen(vehicle_id)
    return {"ok": True}


@app.delete("/api/conversations/{vehicle_id}")
async def clear_conversation(vehicle_id: str):
    vehicle_or_404(vehicle_id)
    store().clear_messages(vehicle_id)
    turns.seen(vehicle_id)
    return {"ok": True}


# --- черновики заявок ---
def draft_or_404(draft_id: str) -> dict:
    draft = store().draft(draft_id)
    if draft is None:
        raise HTTPException(404, "Черновик не найден")
    return draft


@app.patch("/api/drafts/{draft_id}")
async def patch_draft(draft_id: str, patch: DraftPatch):
    draft = draft_or_404(draft_id)
    if draft["status"] != "draft":
        raise HTTPException(409, "Заявка уже отправлена, править её нельзя")
    if patch.conclusion is not None:
        draft["conclusion"] = patch.conclusion.strip()
    if patch.urgency is not None and patch.urgency != draft["urgency"]:
        draft["urgency"] = patch.urgency
        draft["urgency_basis"] = [*draft.get("urgency_basis", []),
                                  f"Приоритет изменён механиком на «{rules.LABELS[patch.urgency]}»"]
    store().save_draft(draft)
    return draft


@app.post("/api/drafts/{draft_id}/confirm")
async def confirm_draft(draft_id: str, req: ConfirmRequest):
    draft = draft_or_404(draft_id)
    if draft["status"] == "sent":
        raise HTTPException(409, f"Заявка уже отправлена: {draft['ticket_id']}")
    if draft["requires_warning_ack"] and not req.warning_ack:
        raise HTTPException(400, "Запись с помехами: подтвердите, что понимаете предварительный характер вывода")
    vehicle = vehicle_or_404(draft["vehicle_id"])
    return stream_turn(vehicle, session_id=draft["session_id"],
                       text=f"Подтверждаю заявку {draft_id}. Отправь её в ТОиР.",
                       confirmed_draft_id=draft_id, warning_ack=req.warning_ack,
                       profile=req.profile.model_dump() if req.profile else None)


# --- руководства ---
def manual_or_404(manual_id: str):
    manual = manual_by_id(manual_id)
    if manual is None:
        raise HTTPException(404, "Документа нет в базе знаний")
    return manual


@app.get("/api/manuals/{manual_id}/pages/{page}")
async def manual_page(manual_id: str, page: int):
    manual = manual_or_404(manual_id)
    text = state["index"].page_text(manual_id, page)
    if text is None:
        raise HTTPException(404, f"В документе нет страницы {page}")
    return {
        "manual_id": manual.id, "designation": manual.designation, "title": manual.title, "short": manual.short,
        "engine": ", ".join(manual.engines), "page": page,
        "page_count": state["index"].page_count(manual_id) or manual.pages,
        "image_url": f"/api/manuals/{manual_id}/pages/{page}/image", "text": text,
    }


@app.get("/api/manuals/{manual_id}/pages/{page}/image")
async def manual_page_image(manual_id: str, page: int, q: str = Query(default="", max_length=600)):
    manual_or_404(manual_id)
    png = await asyncio.to_thread(render.page_png, manual_id, page, q)
    if png is None:
        raise HTTPException(404, "Страница недоступна: PDF руководства не подключён к серверу")
    return Response(content=png, media_type="image/png", headers={"Cache-Control": "private, max-age=3600"})


# --- журнал обращений ---
@app.get("/api/audit")
async def audit(limit: int = Query(default=100, ge=1, le=500)):
    """Кто что спросил, что ответил агент, на какие источники сослался."""
    items = store().audit(limit)
    for item in items:
        vehicle = fleet.get_vehicle(item["vehicle_id"])
        item["vehicle_title"] = fleet.title_of(vehicle) if vehicle else item["vehicle_id"]
    return {"items": items}


# --- расчёт стоимости ---
@app.get("/api/usage/summary")
async def usage_summary(since: str | None = None):
    settings = get_settings()
    return {
        **store().usage_summary(since),
        "prices": {"input_per_mtok": settings.price_input, "output_per_mtok": settings.price_output,
                   "cache_read_per_mtok": settings.price_cache_read, "currency": settings.price_currency,
                   "usd_rate": settings.usd_rate},
        "model": state["llm"].model, "mock": state["llm"].is_mock,
    }
