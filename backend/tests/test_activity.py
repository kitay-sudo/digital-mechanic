"""Журнал активности стенда и уведомления в Telegram: входы, вопросы в чате и через API."""
from __future__ import annotations

import asyncio
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app import activity, auth, mechanics
from app.config import get_settings

KEY = "test-key-1"
VISITOR = {"X-Forwarded-For": "10.9.9.9, 203.0.113.7",
           "User-Agent": "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/131.0 Mobile Safari/537.36"}


@pytest.fixture
def sent(monkeypatch):
    """Подмена отправки в Telegram: текст уведомления запоминается в момент события."""
    texts: list[str] = []

    def fake(text: str):
        texts.append(text)
        return asyncio.sleep(0)

    monkeypatch.setattr(activity, "send_telegram", fake)
    monkeypatch.setattr(activity, "_last_event", 0.0)
    return texts


@pytest.fixture
def secured(index, monkeypatch, sent):
    monkeypatch.setenv("AUTH_REQUIRED", "1")
    monkeypatch.setenv("ADMIN_LOGIN", "boss")
    monkeypatch.setenv("ADMIN_PASSWORD", "s3cret")
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    monkeypatch.setenv("INTEGRATION_API_KEYS", KEY)
    auth._admin_fails.clear()
    from app.main import app

    with TestClient(app) as client:
        yield client


def journal() -> list[dict]:
    path = get_settings().data_dir / "activity.log"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []


def test_logins_are_logged_without_pin_and_password(secured, sent):
    m = mechanics.repo().create({"full_name": "Петров Пётр", "pin": "2222"})
    assert secured.post("/api/auth/mechanic", headers=VISITOR, json={"mechanic_id": m["id"], "pin": "0000"}).status_code == 401
    assert secured.post("/api/auth/mechanic", headers=VISITOR, json={"mechanic_id": m["id"], "pin": "2222"}).status_code == 200
    assert secured.post("/api/auth/admin", json={"login": "boss", "password": "wrong"}).status_code == 401
    assert secured.post("/api/auth/admin", json={"login": "boss", "password": "s3cret"}).status_code == 200

    rows = journal()
    assert [r["event"] for r in rows] == ["mechanic_login_failed", "mechanic_login", "admin_login_failed", "admin_login"]
    assert rows[1]["who"] == "Петров Пётр" and rows[1]["ip"] == "203.0.113.7" and rows[1]["time"].endswith("+03:00")
    assert rows[3]["who"] == "логин boss"
    raw = (get_settings().data_dir / "activity.log").read_text(encoding="utf-8")
    assert "2222" not in raw and "0000" not in raw and "s3cret" not in raw and "wrong" not in raw

    # Первое событие после тишины отмечено как начало проверки, следующие нет
    assert len(sent) == 4
    assert sent[0].startswith("Стенд начали проверять") and "Неверный PIN механика" in sent[0]
    assert sent[1].startswith("Вход механика") and "Кто: Петров Пётр" in sent[1]
    assert "Откуда: 203.0.113.7, Chrome, телефон" in sent[1]
    assert not any("s3cret" in t or "2222" in t for t in sent)


def test_questions_in_chat_and_api_are_logged(secured, sent, services):
    m = mechanics.repo().create({"full_name": "Сидоров Сергей", "pin": "3333"})
    assert secured.post("/api/auth/mechanic", json={"mechanic_id": m["id"], "pin": "3333"}).status_code == 200
    r = secured.post("/api/chat", headers=VISITOR, json={
        "vehicle_id": "A101TT77", "text": "Какое давление масла должно быть?", "profile": {"name": "Сидоров Сергей"}})
    assert r.status_code == 200

    h = {"X-API-Key": KEY}
    assert secured.post("/api/v1/agent/ask", headers=h, json={
        "vehicle_id": "A101TT77", "text": "Как проверить зазор клапанов?", "mechanic": "Эксперт через MCP"}).status_code == 200
    assert secured.post("/api/v1/agent/diagnose", headers=h, json={
        "vehicle_id": "A101TT77", "session_id": "S-9003"}).status_code == 200

    rows = {r["event"]: r for r in journal()}
    assert rows["question"]["who"] == "Сидоров Сергей" and rows["question"]["vehicle"] == "A101TT77"
    assert rows["question"]["text"] == "Какое давление масла должно быть?"
    assert rows["api_question"]["who"] == "Эксперт через MCP" and "зазор" in rows["api_question"]["text"]
    assert rows["api_diagnose"]["text"] == "проверка S-9003"
    assert any(t.startswith("Вопрос в чате") and "Текст: Какое давление масла" in t for t in sent)


def test_activity_log_failure_does_not_break_login(secured, monkeypatch):
    def broken(_record):
        raise OSError("диск переполнен")

    monkeypatch.setattr(activity, "_write", broken)
    m = mechanics.repo().create({"full_name": "Петров Пётр", "pin": "2222"})
    assert secured.post("/api/auth/mechanic", json={"mechanic_id": m["id"], "pin": "2222"}).status_code == 200


async def test_telegram_is_sent_only_when_configured(monkeypatch):
    calls: list[httpx.Request] = []
    transport = httpx.MockTransport(lambda req: calls.append(req) or httpx.Response(200, json={"ok": True}))
    real = httpx.AsyncClient
    monkeypatch.setattr(activity.httpx, "AsyncClient", lambda **kw: real(transport=transport, **kw))

    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    await activity.send_telegram("проверка")
    assert calls == []

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "42")
    await activity.send_telegram("Вход механика")
    assert len(calls) == 1 and calls[0].url.path == "/bot123:abc/sendMessage"
    assert json.loads(calls[0].content) == {"chat_id": "42", "text": "Вход механика", "disable_web_page_preview": True}


async def test_telegram_failure_is_quiet(monkeypatch):
    def down(_req):
        raise httpx.ConnectError("нет сети")

    real = httpx.AsyncClient
    monkeypatch.setattr(activity.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(down), **kw))
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "42")
    await activity.send_telegram("Вход механика")
