"""HTTP-сервер «Цифрового механика». Контракт описан в docs/api.md."""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response, StreamingResponse
from pydantic import BaseModel, Field, model_validator

from . import alerts, clients, fleet, rules, stt, turns, uploads
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
        # Где распознаётся голос: на сервере (запись с индикацией, любой браузер) или в браузере
        "stt": {"server": bool(settings.stt_base_url), "model": settings.stt_model if settings.stt_base_url else None},
    }


@app.get("/api/fleet")
async def get_fleet():
    return fleet.fleet(store().tickets_by_vehicle())


@app.get("/api/vehicles/{vehicle_id}")
async def get_vehicle(vehicle_id: str):
    return fleet.detail(vehicle_or_404(vehicle_id), store().tickets(vehicle_id))


# --- чат ---
class Profile(BaseModel):
    """Механик: уровень подачи и кто сейчас работает (смены: в журнале видно, кто спрашивал)."""
    level: str = Field(default="expert", pattern="^(expert|novice)$")
    name: str | None = Field(default=None, max_length=60)


class ChatRequest(BaseModel):
    vehicle_id: str = Field(min_length=1)
    session_id: str | None = None
    text: str = Field(default="", max_length=2000)
    # Фото узла: data URL снимков, уменьшенных в браузере
    images: list[str] = Field(default_factory=list, max_length=uploads.MAX_PHOTOS)
    profile: Profile | None = None

    @model_validator(mode="after")
    def has_content(self):
        if not self.text.strip() and not self.images:
            raise ValueError("Пустое сообщение: нужен текст или фото")
        return self


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
    try:
        photos = uploads.save(req.images, get_settings().data_dir) if req.images else []
    except uploads.PhotoError as exc:
        raise HTTPException(400, str(exc)) from exc
    return stream_turn(vehicle, session_id=session_id, text=req.text.strip(), photos=photos,
                       profile=req.profile.model_dump() if req.profile else None)


@app.get("/api/uploads/{name}")
async def uploaded_photo(name: str):
    path = uploads.path_of(name, get_settings().data_dir)
    if path is None:
        raise HTTPException(404, "Фото не найдено")
    return FileResponse(path, media_type=uploads.media_type(name), headers={"Cache-Control": "private, max-age=86400"})


@app.get("/api/conversations/{vehicle_id}")
async def conversation(vehicle_id: str):
    vehicle_or_404(vehicle_id)
    return {"messages": store().messages(vehicle_id), "turn": turns.status(vehicle_id),
            "marks": store().marks(vehicle_id), "reports": store().reports_by_message(vehicle_id)}


class MarkRequest(BaseModel):
    key: str = Field(pattern=r"^m_[0-9]+:(checks|repair)$")
    index: int = Field(ge=0, le=50)
    done: bool
    author: str | None = Field(default=None, max_length=60)


@app.put("/api/conversations/{vehicle_id}/marks")
async def mark_step(vehicle_id: str, req: MarkRequest):
    """Механик отметил шаг сделанным (или снял отметку). Отметки видны сменщику и агенту."""
    vehicle_or_404(vehicle_id)
    store().set_mark(vehicle_id, req.key, req.index, req.done, (req.author or "").strip() or None)
    return {"marks": store().marks(vehicle_id)}


class ReportRequest(BaseModel):
    message_id: str = Field(pattern=r"^m_[0-9]+$")
    reason: str = Field(min_length=1, max_length=80)
    text: str = Field(default="", max_length=1000)
    author: str | None = Field(default=None, max_length=60)


@app.post("/api/reports")
async def report_problem(req: ReportRequest):
    """Механик сообщает в поддержку о проблеме с ответом: случай появляется в журнале у администратора."""
    message = store().message(int(req.message_id[2:]))
    if message is None or message["role"] != "assistant":
        raise HTTPException(404, "Ответ агента не найден")
    author = (req.author or "").strip() or None
    report = store().add_report(int(req.message_id[2:]), message["vehicle_id"], req.reason.strip(), req.text.strip(), author)
    vehicle = fleet.get_vehicle(message["vehicle_id"]) or {"vehicle_id": message["vehicle_id"]}
    gap = alerts.gap_of(message, report)
    details = req.reason + (f": {req.text.strip()}" if req.text.strip() else "") + (f" (механик {author})" if author else "")
    alerts.notify(get_settings().alert_webhook_url, gap, vehicle, details, message.get("text", ""), report["created_at"])
    return {"report": report}


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


# --- голос ---
MAX_AUDIO = 10 * 1024 * 1024


@app.post("/api/stt")
async def speech_to_text(request: Request, seconds: float = Query(default=0, ge=0, le=600)):
    """Распознаёт фразу механика. Тело запроса — запись из браузера (audio/webm, audio/mp4 и др.)."""
    settings = get_settings()
    if not settings.stt_base_url:
        raise HTTPException(409, "Распознавание речи на сервере не настроено: голос распознаёт браузер.")
    audio = await request.body()
    if not audio:
        raise HTTPException(400, "Запись пустая. Нажмите микрофон и повторите.")
    if len(audio) > MAX_AUDIO:
        raise HTTPException(413, "Запись слишком длинная. Скажите короче или разбейте на две фразы.")
    started = time.monotonic()
    try:
        text = await stt.transcribe(audio, request.headers.get("content-type", "audio/webm"), settings)
    except stt.STTError as exc:
        raise HTTPException(502, str(exc)) from exc
    store().log_stt(settings.stt_model, seconds, round(seconds / 60 * settings.stt_price_per_min, 4),
                    int((time.monotonic() - started) * 1000))
    return {"text": text}


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
class ReviewRequest(BaseModel):
    reviewed: bool = True


@app.get("/api/audit")
async def audit(limit: int = Query(default=100, ge=1, le=500)):
    """Кто что спросил, что ответил агент, на какие источники сослался. Случаи без ответа помечены (gap)."""
    items = store().audit(limit)
    for item in items:
        vehicle = fleet.get_vehicle(item["vehicle_id"])
        item["vehicle_title"] = fleet.title_of(vehicle) if vehicle else item["vehicle_id"]
    return {"items": items, "gaps_open": store().open_gaps()}


@app.get("/api/audit/gaps")
async def audit_gaps():
    """Сколько случаев без ответа в руководстве администратор ещё не разобрал: число у пункта «Журнал»."""
    return {"open": store().open_gaps()}


@app.post("/api/audit/{item_id}/review")
async def review_gap(item_id: str, req: ReviewRequest):
    """Администратор отметил случай разобранным или вернул его в работу."""
    match = re.fullmatch(r"m_(\d+)", item_id)
    if not match or not store().is_assistant_message(int(match.group(1))):
        raise HTTPException(404, "Обращение не найдено")
    return {"id": item_id, "reviewed_at": store().set_reviewed(int(match.group(1)), req.reviewed)}


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
