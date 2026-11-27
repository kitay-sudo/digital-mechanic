"""Инструменты администратора и главного механика: посторонний текст в данных диагностики,
сводка раз в день, вопрос администратору, сводка смены, метрики пилота."""
from __future__ import annotations

import asyncio
from datetime import datetime

import httpx
import pytest

from app import alerts, digest, fleet, journal
from app.agent.llm_mock import MockLLM
from app.agent.loop import run_turn
from app.config import get_settings
from app.store import Store

NONE = {"kind": "answer", "text": "В руководствах на двигатель этой машины ответа нет.", "answer": {"not_found": True}}
KB = {"kind": "notice", "text": "Руководства на двигатель ЯМЗ-236М2 не загружены в базу знаний."}


@pytest.fixture
def store(environment):
    return Store(get_settings().db_path)


@pytest.fixture
def posted(monkeypatch):
    sent: list[dict] = []

    async def fake_post(url, body):
        sent.append(body)

    monkeypatch.setattr(alerts, "_post", fake_post)
    return sent


@pytest.fixture
async def client(store):
    from app import main

    main.state["store"] = store
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://test") as c:
        yield c
    main.state.pop("store", None)


def ask(store, vehicle_id, text, payload, author=None, at=None, session="S-1"):
    store.add_message(vehicle_id, session, "user", {"text": text, **({"author": author} if author else {})})
    message = store.add_message(vehicle_id, session, "assistant", payload)
    if at:
        store._exec("UPDATE messages SET created_at=? WHERE id IN (?, ?)", (at, int(message["id"][2:]), int(message["id"][2:]) - 1))
    return message["id"]


async def turn(store, index, vehicle_id, session_id, text):
    events = []

    async def emit(event):
        events.append(event)

    await run_turn(vehicle=fleet.get_vehicle(vehicle_id), session_id=session_id, text=text, store=store, index=index,
                   settings=get_settings(), llm=MockLLM(), emit=emit)
    return next(e["message"] for e in reversed(events) if e["type"] == "message")


# --- посторонний текст в данных диагностики ---
def test_flagged_description_is_a_case():
    verdict = {"kind": "verdict", "diagnosis": {"description_flagged": True}, "assessment": {"flags": {}},
               "answer": {"not_found": False, "checks": [{}]}}
    assert alerts.gap_of(verdict)["type"] == "injection"
    # Другой случай важнее: посторонний текст остаётся признаком строки
    assert alerts.gap_of({**verdict, "answer": {"not_found": True}})["type"] == "no_answer"
    assert alerts.gap_of({**verdict, "diagnosis": {"description_flagged": False}}) is None


async def test_injection_reaches_admin_journal(store, index, services, posted, monkeypatch):
    monkeypatch.setenv("ALERT_WEBHOOK_URL", "http://alerts.test/hook")
    get_settings.cache_clear()
    # В описании проверки S-9003 есть указания для агента
    message = await turn(store, index, "A101TT77", "S-9003", "Получи результат диагностики")
    await asyncio.gather(*alerts._tasks)
    assert message["kind"] == "verdict" and message["diagnosis"]["description_flagged"]
    found = journal.page(store, {"type": "injection"})
    assert found["total"] == 1 and found["items"][0]["injection"] and found["items"][0]["status"] == "new"
    assert journal.open_count(store) >= 1
    assert not [p for p in posted if p.get("type") == "injection"]  # не срочно: ждёт сводки за день


# --- когда уведомлять ---
def test_urgent_goes_now_rest_waits_for_digest(monkeypatch):
    monkeypatch.delenv("ALERT_MODE", raising=False)
    assert alerts.alert_mode() == "digest"
    assert alerts.sends_now("kb_missing") and alerts.sends_now("ml_mismatch")
    assert not alerts.sends_now("no_answer") and not alerts.sends_now("report") and not alerts.sends_now("injection")
    monkeypatch.setenv("ALERT_MODE", "instant")
    assert alerts.sends_now("no_answer") and alerts.sends_now("injection")


async def test_notify_respects_mode(posted, monkeypatch):
    vehicle = fleet.get_vehicle("A101TT77")
    gap = alerts.gap_of(NONE)
    alerts.notify("http://alerts.test/hook", gap, vehicle, "вопрос", "ответ", "2026-11-27T10:00:00+03:00")
    alerts.notify("http://alerts.test/hook", alerts.gap_of(KB), vehicle, "вопрос", KB["text"], "2026-11-27T10:00:00+03:00")
    await asyncio.gather(*alerts._tasks)
    assert [p["type"] for p in posted] == ["kb_missing"]
    monkeypatch.setenv("ALERT_MODE", "instant")
    alerts.notify("http://alerts.test/hook", gap, vehicle, "вопрос", "ответ", "2026-11-27T10:00:00+03:00")
    await asyncio.gather(*alerts._tasks)
    assert [p["type"] for p in posted] == ["kb_missing", "no_answer"]


# --- сводка за день ---
def _local(text: str) -> datetime:
    return datetime.fromisoformat(text).astimezone(journal.local_tz())


def test_digest_text_lists_open_cases_of_the_day(store):
    day = "2026-11-27"
    ask(store, "B202TT77", "Как проверить турбину?", NONE, "Иванов", f"{day}T09:00:00+03:00")
    ask(store, "C303TT77", "как проверить ТУРБИНУ", NONE, "Петров", f"{day}T11:00:00+03:00")
    reviewed = ask(store, "A101TT77", "Расход топлива у самолёта", NONE, None, f"{day}T12:00:00+03:00")
    journal.set_status(store, [reviewed], "reviewed")
    ask(store, "A101TT77", "Вчерашний вопрос", NONE, None, "2026-11-26T12:00:00+03:00")
    summary = digest.build(store, _local(f"{day}T20:00:00+03:00").date())
    text = summary["text"]
    assert text.startswith("Сводка за 27.11.2026") and "Вопросов механиков: 3" in text
    assert summary["cases"] == 1 and "повторилось 2 раз" in text and "C303TT77" in text and "механик Петров" in text
    assert "самолёта" not in text  # разобранное в сводку не попадает
    assert "Всего в журнале ждут разбора: 2" in text  # вчерашний неразобранный тоже ждёт


async def test_digest_is_sent_once_after_digest_time(store, posted, monkeypatch):
    monkeypatch.setenv("DIGEST_TIME", "18:00")
    ask(store, "B202TT77", "Как проверить турбину?", NONE, at="2026-11-27T09:00:00+03:00")
    url = "http://alerts.test/hook"
    assert await digest.tick(store, url, _local("2026-11-27T17:59:00+03:00")) == []
    sent = await digest.tick(store, url, _local("2026-11-27T18:00:30+03:00"))
    assert len(sent) == 1 and posted[-1]["type"] == "digest" and "турбину" in posted[-1]["text"]
    assert await digest.tick(store, url, _local("2026-11-27T19:00:00+03:00")) == []  # не повторяется
    assert digest.sent_at(store, _local("2026-11-27T19:00:00+03:00").date())
    # Пустой день — без сообщения
    assert await digest.tick(store, url, _local("2026-11-28T18:01:00+03:00")) == []
    monkeypatch.setenv("ALERT_MODE", "instant")
    ask(store, "B202TT77", "Ещё вопрос", NONE, at="2026-11-29T09:00:00+03:00")
    assert await digest.tick(store, url, _local("2026-11-29T18:01:00+03:00")) == []  # сводка только в режиме digest
    assert await digest.tick(store, "", _local("2026-11-30T18:01:00+03:00")) == []


async def test_agent_failures_are_sent_at_once(store, posted):
    url = "http://alerts.test/hook"
    old = store.start_turn("A101TT77", "S-1")
    store.finish_turn(old, "error", 100, False)
    assert await digest.tick(store, url, _local("2026-11-27T10:00:00+03:00")) == []  # о старых сбоях не пишем
    for vehicle_id in ("A101TT77", "B202TT77"):
        failed = store.start_turn(vehicle_id, "S-1")
        store.finish_turn(failed, "error", 100, False)
    ok = store.start_turn("A101TT77", "S-1")
    store.finish_turn(ok, "answer", 100, False)
    sent = await digest.tick(store, url, _local("2026-11-27T10:01:00+03:00"))
    assert len(sent) == 1 and "Сбой агента: 2" in sent[0] and "B202TT77" in sent[0] and posted[-1]["type"] == "failure"
    assert await digest.tick(store, url, _local("2026-11-27T10:02:00+03:00")) == []


def test_bad_digest_time_falls_back(monkeypatch):
    monkeypatch.setenv("DIGEST_TIME", "25:99")
    assert digest.digest_time().strftime("%H:%M") == "18:00"
    monkeypatch.setenv("DIGEST_TIME", "7:30")
    assert digest.digest_time().strftime("%H:%M") == "07:30"


async def test_digest_endpoint(client, store):
    ask(store, "B202TT77", "Как проверить турбину?", NONE)
    r = await client.get("/api/audit/digest")
    data = r.json()
    assert r.status_code == 200 and data["mode"] == "digest" and data["time"] == "18:00" and data["cases"] == 1
    assert "турбину" in data["text"] and data["sent_at"] is None
    assert (await client.get("/api/audit/digest", params={"day": "2026-13-40"})).status_code == 400


# --- вопрос администратору напрямую ---
async def test_admin_message_is_a_case_from_mechanic(client, store, posted, monkeypatch):
    monkeypatch.setenv("ALERT_WEBHOOK_URL", "http://alerts.test/hook")
    monkeypatch.setenv("ALERT_MODE", "instant")
    get_settings.cache_clear()
    r = await client.post("/api/admin-messages", json={"vehicle_id": "A101TT77", "text": "  Нет щупа на посту 2  ",
                                                        "author": "Петров"})
    assert r.status_code == 200 and r.json()["id"].startswith("a_") and r.json()["created_at"]
    r2 = await client.post("/api/admin-messages", json={"text": "Планшет не заряжается"})
    assert r2.status_code == 200
    await asyncio.gather(*alerts._tasks)
    assert "Механик Петров написал администратору" in posted[0]["text"] and "Нет щупа на посту 2" in posted[0]["text"]
    assert posted[0]["type"] == "report" and len(posted) == 2
    rows = journal.page(store)["items"]
    first = next(i for i in rows if i["id"] == r.json()["id"])
    assert first["gap"]["type"] == "report" and first["gap"]["label"] == "От механика" and first["status"] == "new"
    assert first["source"] == "admin" and first["author"] == "Петров" and first["question"] == "Нет щупа на посту 2"
    assert first["answer"] == "" and first["vehicle_title"]
    assert next(i for i in rows if i["id"] == r2.json()["id"])["vehicle_id"] is None
    assert journal.page(store, {"mechanic": "Петров"})["total"] == 1
    assert journal.page(store, {"type": "report"})["total"] == 2
    card = (await client.get(f"/api/audit/{r.json()['id']}")).json()
    assert card["question"] == "Нет щупа на посту 2" and card["reports"] == []
    await client.post("/api/audit/status", json={"ids": [r.json()["id"]], "status": "reviewed"})
    assert (await client.get("/api/audit/gaps")).json() == {"open": 1}
    # Проверка входа
    assert (await client.post("/api/admin-messages", json={"text": "   "})).status_code == 400
    assert (await client.post("/api/admin-messages", json={"text": ""})).status_code == 422
    assert (await client.post("/api/admin-messages", json={"text": "х" * 1001})).status_code == 422
    assert (await client.post("/api/admin-messages", json={"text": "Вопрос", "vehicle_id": "НЕТ"})).status_code == 404


async def test_admin_message_waits_for_digest_by_default(client, posted, monkeypatch):
    monkeypatch.setenv("ALERT_WEBHOOK_URL", "http://alerts.test/hook")
    get_settings.cache_clear()
    assert (await client.post("/api/admin-messages", json={"text": "Вопрос"})).status_code == 200
    await asyncio.gather(*alerts._tasks)
    assert posted == []


async def test_report_row_shows_message_author(store):
    message = ask(store, "A101TT77", "Какой зазор клапанов?", {"kind": "answer", "text": "0,25 мм",
                                                                "answer": {"not_found": False, "checks": [{}]}}, "Иванов")
    store.add_report(int(message[2:]), "A101TT77", "Ответ неверный", "", "Петров")
    row = journal.page(store)["items"][0]
    # Вопрос задал Иванов, о проблеме сообщил Петров: строка случая показывает Петрова
    assert row["author"] == "Иванов" and row["report"]["author"] == "Петров"
    assert journal.page(store, {"mechanic": "Петров"})["total"] == 1
