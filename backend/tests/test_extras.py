"""Доработки после Q&A с заказчиком 27.11: журнал для администратора, фото узла, голос на сервере,
расхождения в таблицах руководства."""
from __future__ import annotations

import asyncio
import base64

import httpx
import pytest

from app import alerts, conflicts, fleet, stt, uploads
from app.agent import json_protocol
from app.agent.llm_mock import MockLLM
from app.agent.llm_openai import OpenAICompatLLM
from app.agent.loop import run_turn
from app.config import get_settings
from app.store import Store

# Самый маленький настоящий JPEG (1×1): сервер проверяет сигнатуру файла
JPEG = base64.b64decode(
    "/9j/4AAQSkZJRgABAQEASABIAAD/2wBDAP//////////////////////////////////////////////////////////////////////"
    "////////////////wgALCAABAAEBAREA/8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAgBAQABPxA="
)
JPEG_URL = "data:image/jpeg;base64," + base64.b64encode(JPEG).decode()


@pytest.fixture
def store(environment):
    return Store(get_settings().db_path)


class RecordingLLM(MockLLM):
    """Заглушка модели, которая запоминает, что ей передали."""

    def __init__(self):
        self.seen: list[list[dict]] = []

    async def complete(self, system, messages, tools, schema):
        self.seen.append(messages)
        return await super().complete(system, messages, tools, schema)


async def turn(store, index, vehicle_id, session_id, text, llm=None, **kw):
    events = []

    async def emit(event):
        events.append(event)

    await run_turn(vehicle=fleet.get_vehicle(vehicle_id), session_id=session_id, text=text, store=store, index=index,
                   settings=get_settings(), llm=llm or MockLLM(), emit=emit, **kw)
    messages = [e["message"] for e in events if e["type"] == "message"]
    return (messages[-1] if messages else None), events


# --- журнал: случаи без ответа ---
def test_gap_kinds():
    assert alerts.gap_of({"kind": "answer", "answer": {"not_found": True}})["type"] == "no_answer"
    assert alerts.gap_of({"kind": "verdict", "answer": {"recommendation_text": "Рекомендация на дефектовку"}})["type"] == "no_answer"
    assert alerts.gap_of({"kind": "verdict", "assessment": {"flags": {"engine_mismatch": True}},
                          "answer": {"not_found": True}})["type"] == "ml_mismatch"
    assert alerts.gap_of({"kind": "notice", "text": "Руководства на двигатель X не загружены в базу знаний"})["type"] == "kb_missing"
    assert alerts.gap_of({"kind": "answer", "answer": {"not_found": False, "checks": [{}]}}) is None
    assert alerts.gap_of({"kind": "ticket_created", "answer": {"not_found": True}}) is None


async def test_no_answer_is_flagged_for_admin_and_can_be_reviewed(store, index, services, monkeypatch):
    sent = []

    async def fake_post(url, body):
        sent.append((url, body))

    monkeypatch.setenv("ALERT_WEBHOOK_URL", "http://alerts.test/hook")
    get_settings.cache_clear()
    monkeypatch.setattr(alerts, "_post", fake_post)

    message, _ = await turn(store, index, "A101TT77", "S-9003", "Какой расход топлива у самолёта на взлёте?")
    await asyncio.gather(*alerts._tasks)
    assert message["answer"]["not_found"]
    # Администратор узнаёт сразу: машина, двигатель и вопрос механика
    assert sent and sent[0][0] == "http://alerts.test/hook"
    assert "Нет ответа в руководстве" in sent[0][1]["text"] and "ЯМЗ-236М2" in sent[0][1]["text"]
    assert "самолёта" in sent[0][1]["question"]

    item = store.audit()[0]
    assert item["gap"]["type"] == "no_answer" and item["gap"]["reviewed_at"] is None
    assert store.open_gaps() == 1
    number = int(item["id"].split("_")[1])
    assert store.set_reviewed(number, True)
    assert store.audit()[0]["gap"]["reviewed_at"] and store.open_gaps() == 0
    store.set_reviewed(number, False)
    assert store.open_gaps() == 1


async def test_ordinary_answer_is_not_flagged(store, index, services, monkeypatch):
    sent = []

    async def fake_post(url, body):
        sent.append(body)

    monkeypatch.setenv("ALERT_WEBHOOK_URL", "http://alerts.test/hook")
    get_settings.cache_clear()
    monkeypatch.setattr(alerts, "_post", fake_post)
    message, _ = await turn(store, index, "A101TT77", "S-9003", "Какое давление масла должно быть в системе смазки?")
    await asyncio.gather(*alerts._tasks)
    assert not message["answer"]["not_found"] and not sent
    assert store.audit()[0]["gap"] is None


# --- фото узла ---
def test_photo_is_checked_and_saved(tmp_path):
    saved = uploads.save([JPEG_URL], tmp_path)
    assert saved[0]["url"].startswith("/api/uploads/") and uploads.path_of(saved[0]["id"], tmp_path)
    block = uploads.image_block(saved[0]["id"], tmp_path)
    assert block["type"] == "image" and block["source"]["media_type"] == "image/jpeg"
    with pytest.raises(uploads.PhotoError):
        uploads.save(["data:image/png;base64," + base64.b64encode(b"not a png").decode()], tmp_path)
    with pytest.raises(uploads.PhotoError):
        uploads.save(["data:text/html;base64,PGgxPg=="], tmp_path)
    with pytest.raises(uploads.PhotoError):
        uploads.save([JPEG_URL] * 4, tmp_path)
    assert uploads.path_of("../app.sqlite", tmp_path) is None


async def test_photo_reaches_the_model_and_the_chat(store, index, services):
    photos = uploads.save([JPEG_URL], get_settings().data_dir)
    llm = RecordingLLM()
    await turn(store, index, "A101TT77", "S-9003", "Что это за подтёк?", llm=llm, photos=photos)
    first = llm.seen[0][0]["content"]
    assert isinstance(first, list) and any(b["type"] == "image" for b in first)
    assert "Что это за подтёк?" in first[-1]["text"]
    user = next(m for m in store.messages("A101TT77") if m["role"] == "user")
    assert user["images"][0]["id"] == photos[0]["id"]

    # Следующий вопрос без фото: модель всё ещё видит снимок из недавнего сообщения
    llm2 = RecordingLLM()
    await turn(store, index, "A101TT77", "S-9003", "А на фото видна трещина?", llm=llm2)
    again = llm2.seen[0][0]["content"]
    assert isinstance(again, list) and any(b["type"] == "image" for b in again)
    assert "приложил фото: 1" in again[-1]["text"]


def test_photo_in_other_model_layers():
    block = {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": "QUJD"}}
    messages = [{"role": "user", "content": [block, {"type": "text", "text": "[Сообщение механика]\nЧто на фото?"}]}]
    rendered = json_protocol.render(messages)
    assert "Что на фото?" in rendered and "Твой предыдущий ответ" not in rendered and "фото" in rendered
    native = OpenAICompatLLM._native_messages("система", messages)
    parts = native[1]["content"]
    assert native[1]["role"] == "user" and parts[0]["image_url"]["url"].startswith("data:image/jpeg;base64,")


# --- голос через сервер ---
async def test_speech_is_sent_in_openai_format(monkeypatch):
    seen = {}

    async def fake_post(self, url, headers=None, data=None, files=None):
        seen.update(url=url, headers=headers, data=data, files=files)
        return httpx.Response(200, json={"text": "Какой момент затяжки крышек коренных подшипников?"})

    monkeypatch.setenv("STT_BASE_URL", "https://stt.test/v1")
    monkeypatch.setenv("STT_API_KEY", "k")
    get_settings.cache_clear()
    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    text = await stt.transcribe(b"\x1aE\xdf\xa3", "audio/webm;codecs=opus", get_settings())
    assert text.startswith("Какой момент затяжки")
    assert seen["url"] == "https://stt.test/v1/audio/transcriptions" and seen["headers"]["Authorization"] == "Bearer k"
    assert seen["data"]["language"] == "ru" and "ЯМЗ" in seen["data"]["prompt"]
    assert seen["files"]["file"][0] == "speech.webm" and seen["files"]["file"][2] == "audio/webm"


async def test_speech_errors_are_readable(monkeypatch):
    async def denied(self, url, **kw):
        return httpx.Response(401, json={"detail": "bad key"})

    monkeypatch.setenv("STT_BASE_URL", "https://stt.test/v1")
    get_settings.cache_clear()
    monkeypatch.setattr(httpx.AsyncClient, "post", denied)
    with pytest.raises(stt.STTError, match="Ключ"):
        await stt.transcribe(b"x", "audio/webm", get_settings())


def test_phantom_phrases_from_silence_are_dropped():
    assert stt.clean("Субтитры сделал DimaTorzok") == ""
    assert stt.clean("  Продолжение следует...  ") == ""
    assert stt.clean("Метки не совпадают, создай заявку") == "Метки не совпадают, создай заявку"


# --- расхождение в таблице руководства ---
def test_conflict_statement_found_in_table_rows():
    page = "\n".join([
        "Приложение В - Моменты затяжки", "Резьбовое соединение", "Момент затяжки Н·м (кгс·м)",
        "Болты крепления крышек коренных ", "подшипников: ", " ", " вертикальные ", "430-470 (43-47) ",
        " горизонтальные ", "100-120 (10-12) ", "Болты крепления крышек шатунов 200-220 (20-22)",
        # Таблица длинная, как в руководстве: целиком она в цитату не помещается
        "Болты крепления картера маховика 100-125 (10-12,5)", "Болты крепления маховика 200-220 (20-22)",
        "Гайки крепления головки цилиндров 240-260 (24-26)", "Болты крепления осей коромысел 120-150 (12-15)",
        "Гайки шпилек выпускных коллекторов 40-55 (4-5,5)", "Болты крепления масляного насоса 45-62 (4,5-6,2)",
    ])
    quote = conflicts._sentence(page, ["430-470", "43-47"])
    assert quote and "коренных подшипников" in quote and "430-470 (43-47)" in quote and "" not in quote
    assert "горизонтальные" not in quote


# --- смены, память по машине, повтор после ремонта, сообщение в поддержку ---
async def test_mechanic_name_reaches_chat_journal_and_agent(store, index, services):
    llm = RecordingLLM()
    await turn(store, index, "A101TT77", "S-9003", "Какое давление масла должно быть?", llm=llm,
               profile={"level": "expert", "name": "Иванов"})
    user = next(m for m in store.messages("A101TT77") if m["role"] == "user")
    assert user["author"] == "Иванов"
    assert store.audit()[0]["author"] == "Иванов"
    context = llm.seen[0][0]["content"]
    assert "Сейчас пишет механик Иванов" in context and "[Работа по машине]" in context

    # Сменщик продолжает: агент видит, кто писал до него и что отмечено сделанным
    answer = next(m for m in store.messages("A101TT77") if m["role"] == "assistant")
    assert answer["answer"]["checks"], "в ответе должны быть шаги проверки"
    store.set_mark("A101TT77", f"{answer['id']}:checks", 0, True, "Иванов")
    llm2 = RecordingLLM()
    await turn(store, index, "A101TT77", "S-9003", "Что дальше?", llm=llm2, profile={"level": "expert", "name": "Петров"})
    context2 = llm2.seen[0][0]["content"]
    assert "Сейчас пишет механик Петров" in context2
    assert "механик: Иванов" in context2 and "Механики отметили сделанным" in context2
    assert answer["answer"]["checks"][0]["text"] in context2


def test_step_marks_are_shared_and_cleared_with_chat(store):
    store.set_mark("A101TT77", "m_1:checks", 2, True, "Иванов")
    marks = store.marks("A101TT77")
    assert marks["m_1:checks"]["2"]["author"] == "Иванов" and marks["m_1:checks"]["2"]["at"]
    store.set_mark("A101TT77", "m_1:checks", 2, False, "Иванов")
    assert store.marks("A101TT77") == {}
    store.set_mark("A101TT77", "m_1:repair", 0, True, None)
    store.clear_messages("A101TT77")
    assert store.marks("A101TT77") == {}


def test_repeat_after_repair_is_detected():
    from app import rules

    diagnosis = {"status": "anomaly", "anomaly_type": "F02"}
    tickets = [{"ticket_id": "TKT-0007", "session_id": "S-9001", "anomaly_type": "F02",
                "created_at": "2026-05-14T10:00:00+03:00"}]
    text = rules.repeat_after_repair(diagnosis, tickets, "S-9003")
    assert "TKT-0007" in text and "14.05.2026" in text and "после ремонта" in text
    assert rules.repeat_after_repair(diagnosis, tickets, "S-9001") is None  # та же проверка — не повтор
    assert rules.repeat_after_repair({"status": "anomaly", "anomaly_type": "F01"}, tickets, "S-9003") is None
    assert rules.repeat_after_repair({"status": "normal", "anomaly_type": None}, tickets, "S-9003") is None


async def test_past_tickets_are_in_context_months_later(store, index, services):
    store.add_ticket({"ticket_id": "TKT-0007", "vehicle_id": "A101TT77", "session_id": "S-9001", "anomaly_type": "F02",
                      "conclusion": "Низкое давление масла, замена насоса.", "urgency": "high",
                      "operations": ["Снять и проверить масляный насос"], "spare_parts": ["Масляный насос"],
                      "references": []})
    llm = RecordingLLM()
    message, _ = await turn(store, index, "A101TT77", "S-9003", "Получи результат диагностики", llm=llm)
    context = llm.seen[0][0]["content"]
    assert "TKT-0007" in context and "Снять и проверить масляный насос" in context
    # Код сам предупреждает механика: тот же тип уже ремонтировали
    assert any("Повтор после ремонта" in w and "TKT-0007" in w for w in message["assessment"]["warnings"])


async def test_mechanic_report_reaches_admin(store, index, services, monkeypatch):
    sent = []

    async def fake_post(url, body):
        sent.append(body)

    monkeypatch.setenv("ALERT_WEBHOOK_URL", "http://alerts.test/hook")
    get_settings.cache_clear()
    monkeypatch.setattr(alerts, "_post", fake_post)
    await turn(store, index, "A101TT77", "S-9003", "Какое давление масла должно быть?")
    item = store.audit()[0]
    assert item["gap"] is None
    number = int(item["id"].split("_")[1])
    store.set_reviewed(number, True)
    store.add_report(number, "A101TT77", "Ответ неверный", "На стр. 19 другая цифра", "Петров")
    item = store.audit()[0]
    assert item["gap"]["type"] == "report" and item["gap"]["reviewed_at"] is None  # сообщение вернуло случай в работу
    assert item["report"]["author"] == "Петров" and store.open_gaps() == 1
    assert store.reports_by_message("A101TT77")[item["id"]]["reason"] == "Ответ неверный"


def test_conflict_quote_drops_glued_table_header():
    page = ("2 При измерении размера отверстий болты крепления крышек коренных подшипников должны быть затянуты "
            "моментом силы от 421 до 461 Н·м ( от 43 до 47 кгс·м), стяжные болты моментом от 88 до 118 Н·м. "
            "контроля мм без без или")
    quote = conflicts._sentence(page, ["421 до 461", "43 до 47"])
    assert quote.endswith("от 88 до 118 Н·м.") and "контроля" not in quote


def test_context_time_is_local_not_server_utc():
    from app.agent.prompt import when

    assert when("2026-11-27T16:29:05+00:00") == "27.11.2026 19:29"  # сервер в контейнере живёт по UTC
