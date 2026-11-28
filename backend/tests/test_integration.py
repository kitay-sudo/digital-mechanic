"""API для внешних систем (/api/v1), механики и вход по PIN, роли и закрытые маршруты."""
from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from app import auth, clients, fleet, mechanics, turns
from app.config import get_settings

KEY = "test-key-1"
H = {"X-API-Key": KEY}


@pytest.fixture
def api(index, monkeypatch):
    """Сервер с ключом внешней системы, вход выключен (как в conftest)."""
    monkeypatch.setenv("INTEGRATION_API_KEYS", f"other-key, {KEY}")
    from app.main import app

    with TestClient(app) as client:
        yield client


@pytest.fixture
def secured(index, monkeypatch):
    """Сервер с включённым входом."""
    monkeypatch.setenv("AUTH_REQUIRED", "1")
    monkeypatch.setenv("ADMIN_LOGIN", "boss")
    monkeypatch.setenv("ADMIN_PASSWORD", "s3cret")
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    monkeypatch.setenv("INTEGRATION_API_KEYS", KEY)
    auth._admin_fails.clear()
    from app.main import app

    with TestClient(app) as client:
        yield client


# --- ключ API ---
def test_api_key_missing_wrong_and_right(api):
    assert api.get("/api/v1/vehicles").status_code == 401
    wrong = api.get("/api/v1/vehicles", headers={"X-API-Key": "nope"})
    assert wrong.status_code == 403 and "Ключ" in wrong.json()["detail"]
    ok = api.get("/api/v1/vehicles", headers=H)
    assert ok.status_code == 200 and ok.json()["total"] == 7  # тестовый парк из файла попал в базу


def test_api_without_keys_is_off(index, monkeypatch):
    monkeypatch.delenv("INTEGRATION_API_KEYS", raising=False)
    from app.main import app

    with TestClient(app) as client:
        r = client.get("/api/v1/vehicles", headers=H)
    assert r.status_code == 503 and "INTEGRATION_API_KEYS" in r.json()["detail"]


def test_docs_show_only_external_api(api):
    schema = api.get("/api/openapi.json").json()
    assert schema["paths"] and all(p.startswith("/api/v1/") for p in schema["paths"])
    assert "X-API-Key" in str(schema["components"]["securitySchemes"])
    assert api.get("/api/docs").status_code == 200


# --- машины из учётной системы ---
def test_vehicle_create_validate_and_show_in_fleet(api):
    body = {"vehicle_id": "а 777 мм 77", "engine_model": "ямз-536", "make": "КамАЗ", "model": "КамАЗ-65115",
            "garage_no": "Г-777", "vehicle_type": "грузовой автомобиль", "fuel": "дизель"}
    r = api.post("/api/v1/vehicles", json=body, headers=H)
    assert r.status_code == 201, r.text
    car = r.json()
    assert car["vehicle_id"] == "A777MM77" and car["engine_model"] == "ЯМЗ-536" and car["created"]
    assert car["manuals"] == ["РЭ ЯМЗ-536", "РК ЯМЗ-536"]

    bad = api.post("/api/v1/vehicles", json={**body, "engine_model": "Д-245"}, headers=H)
    assert bad.status_code == 422 and "ЯМЗ-236М2" in bad.json()["allowed"] and "Д-245" in bad.json()["detail"]
    missing = api.post("/api/v1/vehicles", json={"vehicle_id": "B1"}, headers=H)
    assert missing.status_code == 422 and missing.json()["errors"]

    fleet_ids = [v["vehicle_id"] for v in api.get("/api/fleet").json()["vehicles"]]
    assert "A777MM77" in fleet_ids

    again = api.post("/api/v1/vehicles", json={"vehicle_id": "A777MM77", "garage_no": "Г-778"}, headers=H)
    assert again.status_code == 200 and not again.json()["created"]
    assert again.json()["garage_no"] == "Г-778" and again.json()["make"] == "КамАЗ"  # прочие поля не тронуты

    put = api.put("/api/v1/vehicles/A777MM77", json={"engine_model": "ЯМЗ-236М2"}, headers=H)
    assert put.status_code == 200 and put.json()["engine_model"] == "ЯМЗ-236М2"

    gone = api.delete("/api/v1/vehicles/A777MM77", headers=H)
    assert gone.status_code == 200 and not gone.json()["active"]
    assert "A777MM77" not in [v["vehicle_id"] for v in api.get("/api/fleet").json()["vehicles"]]
    assert api.get("/api/vehicles/A777MM77").status_code == 404
    back = api.post("/api/v1/vehicles", json={"vehicle_id": "A777MM77"}, headers=H)
    assert back.status_code == 200 and back.json()["active"]
    assert api.put("/api/v1/vehicles/X000XX00", json={"fuel": "газ"}, headers=H).status_code == 404


# --- проверки от «НейроДВС» ---
RESULT = {"status": "anomaly", "anomaly_type": "F02", "anomaly_title": "Стук клапанов", "anomaly_score": 0.81,
          "confidence": 0.9, "signal_quality": "good", "description": "Стук в зоне ГРМ", "model_version": "neuro-2"}


def test_webhook_check_appears_in_history_and_fleet(api):
    r = api.post("/api/v1/checks", headers=H, json={
        "vehicle_id": "B202TT77", "session_id": "S-NEW-1", "checked_at": "2026-11-27T10:00:00+03:00", **RESULT})
    assert r.status_code == 201 and r.json()["has_result"], r.text
    detail = api.get("/api/vehicles/B202TT77").json()
    assert detail["sessions"][-1]["session_id"] == "S-NEW-1"
    assert detail["last_session"]["anomaly_type"] == "F02"
    brief = next(v for v in api.get("/api/fleet").json()["vehicles"] if v["vehicle_id"] == "B202TT77")
    assert brief["last_session"]["session_id"] == "S-NEW-1" and brief["fleet_status"] != "ok"

    repeat = api.post("/api/v1/checks", headers=H, json={
        "vehicle_id": "B202TT77", "session_id": "S-NEW-1", "checked_at": "2026-11-27T10:00:00+03:00"})
    assert repeat.status_code == 200 and not repeat.json()["created"] and repeat.json()["has_result"]

    unknown = api.post("/api/v1/checks", headers=H, json={
        "vehicle_id": "Z999ZZ99", "session_id": "S-1", "checked_at": "2026-11-27T10:00:00+03:00"})
    assert unknown.status_code == 404
    half = api.post("/api/v1/checks", headers=H, json={
        "vehicle_id": "B202TT77", "session_id": "S-2", "checked_at": "2026-11-27T10:00:00", "status": "anomaly"})
    assert half.status_code == 422 and "signal_quality" in half.json()["detail"]


def test_pending_check_does_not_break_fleet(api, monkeypatch):
    async def down(vehicle_id, session_id):
        raise clients.ServiceError("нет связи")

    monkeypatch.setattr(clients, "diagnose", down)
    r = api.post("/api/v1/checks", headers=H, json={
        "vehicle_id": "A101TT77", "session_id": "S-PEND", "checked_at": "2026-11-28T09:00:00+03:00"})
    assert r.status_code == 201 and not r.json()["has_result"]
    brief = next(v for v in api.get("/api/fleet").json()["vehicles"] if v["vehicle_id"] == "A101TT77")
    assert brief["last_session"]["session_id"] == "S-PEND" and brief["last_session"]["status"] is None
    assert brief["fleet_status"] == "quarantine"  # статус по последней проверке с результатом


async def test_agent_uses_webhook_result_when_ml_does_not_know_check(index, services, monkeypatch):
    from app.agent.llm_mock import MockLLM
    from app.agent.loop import run_turn
    from app.store import Store

    async def unknown(vehicle_id, session_id):
        raise clients.ServiceError("ML-сервис не знает проверку", 404)

    monkeypatch.setattr(clients, "diagnose", unknown)

    fleet.repo().add_check("A101TT77", "S-HOOK", "2026-11-27T12:00:00+03:00", dict(RESULT))
    store = Store(get_settings().db_path)
    events = []

    async def emit(event):
        events.append(event)

    await run_turn(vehicle=fleet.get_vehicle("A101TT77"), session_id="S-HOOK", text="Получи результат диагностики",
                   store=store, index=index, settings=get_settings(), llm=MockLLM(), emit=emit)
    message = next(e["message"] for e in events if e["type"] == "message")
    assert message["kind"] == "verdict" and message["diagnosis"]["anomaly_type"] == "F02"
    step = next(s for s in message["steps"] if s["tool"] == "get_diagnosis")
    assert step["status"] == "done" and "веб-хука" in step["detail"]


# --- настройки подключений ---
def test_integrations_override_env_and_mask_secrets(api, monkeypatch):
    r = api.put("/api/v1/settings/integrations", headers=H, json={
        "ml_url": "http://ml.local:9001/", "alert_webhook_url": "https://chat.example/hooks/SECRET123",
        "toir_token": "tok-abcdefgh-1234"})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["ml_url"] == "http://ml.local:9001"
    assert "SECRET123" not in str(data) and data["alert_webhook_url"].startswith("https://chat.example/")
    assert "tok-abcdefgh" not in str(data) and data["toir_token"].endswith("1234")
    s = get_settings()
    assert s.ml_url == "http://ml.local:9001" and s.alert_webhook_url.endswith("SECRET123") and s.toir_token
    # Показанное скрытое значение не перетирает настоящее, пустое — возвращает .env
    api.put("/api/v1/settings/integrations", headers=H, json={"alert_webhook_url": data["alert_webhook_url"]})
    assert get_settings().alert_webhook_url.endswith("SECRET123")
    api.put("/api/v1/settings/integrations", headers=H, json={"ml_url": ""})
    assert get_settings().ml_url == "http://127.0.0.1:8001"
    bad = api.put("/api/v1/settings/integrations", headers=H, json={"toir_url": "ftp://x"})
    assert bad.status_code == 422 and "ТОиР" in bad.json()["detail"]


def test_model_switch_local_yandex_and_back(api):
    """Администратор меняет модель на экране «Подключения»: действует сразу, ключи скрыты, без полей не сохраняется."""
    from app.main import state

    start = api.get("/api/v1/settings/integrations", headers=H).json()["model"]
    assert start["mode"] == "cloud"
    # Локальной модели без имени не бывает
    bad = api.put("/api/v1/settings/integrations", headers=H, json={"llm_mode": "local", "llm_local_url": "http://gpu.local:11434/v1"})
    assert bad.status_code == 422 and "имя модели" in bad.json()["detail"]
    assert get_settings().llm_mode == "cloud"
    r = api.put("/api/v1/settings/integrations", headers=H, json={
        "llm_mode": "local", "llm_local_url": "http://gpu.local:11434/v1/", "llm_local_model": "qwen2.5:7b"})
    assert r.status_code == 200, r.text
    s = get_settings()
    assert (s.llm_mode, s.llm_provider, s.llm_base_url, s.llm_model) == ("local", "openai", "http://gpu.local:11434/v1", "qwen2.5:7b")
    assert s.price_input == 0 and s.price_output == 0  # локальная модель бесплатна по токенам
    assert state["llm"].name == "openai" and state["llm"].model == "qwen2.5:7b"  # клиент пересоздан без перезапуска
    # Yandex AI Studio: модель собирается из каталога, ключ в ответе скрыт
    r = api.put("/api/v1/settings/integrations", headers=H, json={
        "llm_mode": "yandex", "yandex_folder": "b1gfolder", "yandex_key": "AQVN-secret-key-9876"})
    assert r.status_code == 200, r.text
    model = r.json()["model"]
    assert model["mode"] == "yandex" and "secret-key" not in str(r.json()) and model["yandex"]["key"].endswith("9876")
    s = get_settings()
    assert s.llm_model == "gpt://b1gfolder/yandexgpt/latest" and s.llm_project == "b1gfolder" and s.llm_provider == "openai"
    # Назад в облако из настроек сервера
    r = api.put("/api/v1/settings/integrations", headers=H, json={"llm_mode": "cloud"})
    assert r.status_code == 200 and get_settings().llm_mode == "cloud"
    assert state["llm"].name == start["provider"] or state["llm"].is_mock


# --- приёмник заявок: переходник подключается переменной TICKET_SINK ---
class FakeSink:
    name = "fake"
    sent: list[dict] = []

    def __init__(self, settings):
        self.url = settings.toir_url

    async def create(self, payload: dict) -> dict:
        FakeSink.sent.append(payload)
        return {"ticket_id": "1C-0001", "status": "created"}

    async def health(self) -> bool:
        return True


async def test_ticket_sink_is_pluggable(monkeypatch):
    monkeypatch.setenv("TICKET_SINK", "tests.test_integration:FakeSink")
    get_settings.cache_clear()
    assert isinstance(clients.ticket_sink(), clients.TicketSink)
    assert (await clients.create_ticket({"vehicle_id": "A101TT77"}))["ticket_id"] == "1C-0001"
    assert (await clients.health())["toir"] is True

    monkeypatch.setenv("TICKET_SINK", "tests.nowhere:Sink")
    get_settings.cache_clear()
    with pytest.raises(clients.ServiceError, match="TICKET_SINK"):
        await clients.create_ticket({})


# --- коннектор к агенту ---
def test_agent_ask_and_diagnose_on_mock_model(api, services):
    verdict = api.post("/api/v1/agent/diagnose", headers=H, json={"vehicle_id": "A101TT77", "session_id": "S-9003"})
    assert verdict.status_code == 200, verdict.text
    v = verdict.json()
    assert v["kind"] == "verdict" and v["assessment"]["outcome"] == "anomaly" and v["diagnosis"]["anomaly_type"] == "F02"

    asked = api.post("/api/v1/agent/ask", headers=H, json={
        "vehicle_id": "A101TT77", "text": "Какое давление масла должно быть?", "mechanic": "Иванов Иван"})
    assert asked.status_code == 200, asked.text
    a = asked.json()
    assert a["kind"] == "answer" and a["message_id"].startswith("m_")
    refs = [ref for item in a["answer"]["checks"] + a["answer"]["repair"] for ref in item["refs"]]
    assert refs and all(ref["pdf_page"] for ref in refs)
    messages = api.get("/api/conversations/A101TT77").json()["messages"]
    assert any(m.get("author") == "Иванов Иван" for m in messages)

    draft = api.post("/api/v1/agent/ask", headers=H, json={
        "vehicle_id": "A101TT77", "session_id": "S-9003", "text": "Создай заявку на дефектовку"}).json()
    assert draft["kind"] == "ticket_draft" and not services
    sent = api.post("/api/v1/agent/confirm", headers=H, json={"draft_id": draft["draft"]["draft_id"]})
    assert sent.status_code == 200 and sent.json()["kind"] == "ticket_created" and services


def test_agent_busy_vehicle_is_409(api, services):
    async def block():
        gate = asyncio.Event()

        async def work(emit):
            await gate.wait()

        turns.start("A101TT77", work)

    api.portal.call(block)
    r = api.post("/api/v1/agent/ask", headers=H, json={"vehicle_id": "A101TT77", "text": "Что с машиной?"})
    assert r.status_code == 409 and "отвечает" in r.json()["detail"]
    assert api.post("/api/v1/agent/ask", headers=H, json={"vehicle_id": "Q1Q1Q1", "text": "?"}).status_code == 404


# --- механики и PIN ---
def test_mechanics_pin_is_hashed_and_locks_after_five_errors(api):
    r = api.post("/api/v1/mechanics", headers=H, json={"full_name": "Кузнецов  Андрей", "age": 45, "pin": "4821",
                                                       "level": "novice", "font_size": "large"})
    assert r.status_code == 201, r.text
    m = r.json()
    assert m["full_name"] == "Кузнецов Андрей" and "pin" not in m
    row = mechanics.repo().db.one("SELECT pin_hash FROM mechanics WHERE id=?", (m["id"],))
    assert "4821" not in row["pin_hash"] and row["pin_hash"].startswith("pbkdf2_sha256$")
    other = mechanics.hash_pin("4821")
    assert other != row["pin_hash"] and mechanics.check_pin("4821", other)  # соль своя у каждого хэша

    dup = api.post("/api/v1/mechanics", headers=H, json={"full_name": "кузнецов андрей", "pin": "1234"})
    assert dup.status_code == 409
    assert api.post("/api/v1/mechanics", headers=H, json={"full_name": "Без Пина", "pin": "12a4"}).status_code == 422

    ok = api.post("/api/auth/mechanic", json={"mechanic_id": m["id"], "pin": "4821"})
    assert ok.status_code == 200 and ok.json()["mechanic"]["font_size"] == "large"
    for left in (4, 3, 2, 1):
        wrong = api.post("/api/auth/mechanic", json={"mechanic_id": m["id"], "pin": "0000"})
        assert wrong.status_code == 401 and wrong.json()["attempts_left"] == left
    locked = api.post("/api/auth/mechanic", json={"mechanic_id": m["id"], "pin": "0000"})
    assert locked.status_code == 429 and "минуту" in locked.json()["detail"]
    still = api.post("/api/auth/mechanic", json={"mechanic_id": m["id"], "pin": "4821"})
    assert still.status_code == 429  # пауза действует и для верного PIN

    later = mechanics.repo().login(m["id"], "4821", clock=lambda: 10**10)  # через минуту вход снова открыт
    assert later["id"] == m["id"]

    off = api.delete(f"/api/v1/mechanics/{m['id']}", headers=H)
    assert off.status_code == 200 and not off.json()["active"]
    names = [x["full_name"] for x in api.get("/api/auth/mechanics").json()["items"]]
    assert "Кузнецов Андрей" not in names


def test_demo_seed(index, monkeypatch):
    monkeypatch.setenv("DEMO_SEED", "1")
    repo = mechanics.repo()
    names = [m["full_name"] for m in repo.list()]
    assert names == ["Иванов Иван", "Петров Пётр", "Сидоров Сергей"]
    sidorov = next(m for m in repo.list() if m["full_name"] == "Сидоров Сергей")
    assert sidorov["level"] == "novice" and sidorov["font_size"] == "large"
    assert repo.login(sidorov["id"], "3333")["id"] == sidorov["id"]


# --- вход и роли ---
def test_routes_closed_without_login(secured):
    assert secured.get("/api/fleet").status_code == 401
    assert secured.get("/api/audit").status_code == 401
    assert secured.get("/api/health").status_code == 200
    assert secured.get("/api/auth/me").json() == {"required": True, "role": None, "mechanic": None, "hint": None}
    # Действующий ключ внешней системы открывает служебный доступ (скрипты проверки качества)
    assert secured.get("/api/fleet", headers=H).status_code == 200


def test_mechanic_sees_fleet_but_not_admin_screens(secured):
    m = mechanics.repo().create({"full_name": "Петров Пётр", "pin": "2222"})
    r = secured.post("/api/auth/mechanic", json={"mechanic_id": m["id"], "pin": "2222"})
    assert r.status_code == 200
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie
    assert secured.get("/api/fleet").status_code == 200
    assert secured.get("/api/auth/me").json()["mechanic"]["full_name"] == "Петров Пётр"
    assert secured.get("/api/audit").status_code == 403
    assert secured.get("/api/admin/mechanics").status_code == 403

    # Новый PIN закрывает прежний вход
    mechanics.repo().update(m["id"], {"pin": "9999"})
    assert secured.get("/api/fleet").status_code == 401


def test_admin_login_and_closed_routes(secured):
    assert secured.post("/api/auth/admin", json={"login": "boss", "password": "wrong"}).status_code == 401
    r = secured.post("/api/auth/admin", json={"login": "boss", "password": "s3cret"})
    assert r.status_code == 200 and r.json()["role"] == "admin"
    assert secured.get("/api/audit").status_code == 200
    created = secured.post("/api/admin/mechanics", json={"full_name": "Сидоров Сергей", "pin": "3333"})
    assert created.status_code == 201
    assert secured.get("/api/admin/mechanics").json()["total"] == 1
    integ = secured.get("/api/admin/integrations").json()
    assert integ["api"]["enabled"] and "health" in integ

    secured.post("/api/auth/logout")
    assert secured.get("/api/audit").status_code == 401


def test_forged_cookie_is_rejected(secured):
    token = auth.sign({"role": "admin", "exp": 10**10})
    body, mac = token.split(".")
    forged = auth.sign({"role": "admin", "exp": 10**10}).split(".")[0] + "." + mac[::-1]
    secured.cookies.set(auth.COOKIE, forged)
    assert secured.get("/api/audit").status_code == 401
    secured.cookies.set(auth.COOKIE, token)
    assert secured.get("/api/audit").status_code == 200
    expired = auth.sign({"role": "admin", "exp": 1})
    secured.cookies.set(auth.COOKIE, expired)
    assert secured.get("/api/audit").status_code == 401


def test_admin_login_locks_after_five_errors(secured):
    for _ in range(4):
        assert secured.post("/api/auth/admin", json={"login": "boss", "password": "x"}).status_code == 401
    assert secured.post("/api/auth/admin", json={"login": "boss", "password": "x"}).status_code == 429
    assert secured.post("/api/auth/admin", json={"login": "boss", "password": "s3cret"}).status_code == 429


def test_admin_decision_signed_by_login_and_shift_is_admin_only(secured):
    # Механик пишет администратору; сводка смены и метрики ему закрыты
    m = mechanics.repo().create({"full_name": "Петров Пётр", "pin": "2222"})
    assert secured.post("/api/auth/mechanic", json={"mechanic_id": m["id"], "pin": "2222"}).status_code == 200
    sent = secured.post("/api/admin-messages", json={"text": "Нет щупа на посту 2", "author": "Петров Пётр"})
    assert sent.status_code == 200
    assert secured.get("/api/shift-summary").status_code == 403
    assert secured.get("/api/metrics").status_code == 403
    secured.post("/api/auth/logout")
    # Решение администратора подписывает его вход, даже если браузер прислал чужую фамилию
    assert secured.post("/api/auth/admin", json={"login": "boss", "password": "s3cret"}).status_code == 200
    r = secured.post("/api/audit/status", json={"ids": [sent.json()["id"]], "status": "reviewed", "reviewer": "Петров Пётр"})
    assert r.status_code == 200
    card = secured.get(f"/api/audit/{sent.json()['id']}").json()
    assert card["reviewer"] == "Администратор"
    assert secured.get("/api/shift-summary").status_code == 200


def test_demo_pin_shown_only_while_unchanged(secured, monkeypatch):
    monkeypatch.setenv("DEMO_SEED", "1")
    repo = mechanics.repo()
    repo.seed_demo()
    items = {m["full_name"]: m for m in secured.get("/api/auth/mechanics").json()["items"]}
    assert items["Иванов Иван"]["demo_pin"] == "1111"
    # PIN сменили — в списке его больше нет
    repo.update(items["Иванов Иван"]["id"], {"pin": "9876"})
    items = {m["full_name"]: m for m in secured.get("/api/auth/mechanics").json()["items"]}
    assert items["Иванов Иван"]["demo_pin"] is None and items["Петров Пётр"]["demo_pin"] == "2222"
    # Без демо-режима PIN не отдаются вовсе
    monkeypatch.setenv("DEMO_SEED", "0")
    assert all(m["demo_pin"] is None for m in secured.get("/api/auth/mechanics").json()["items"])


def test_admin_deletes_mechanic(secured):
    m = mechanics.repo().create({"full_name": "Кузнецов Олег", "pin": "4444"})
    assert secured.post("/api/auth/mechanic", json={"mechanic_id": m["id"], "pin": "4444"}).status_code == 200
    secured.post("/api/auth/logout")
    assert secured.post("/api/auth/admin", json={"login": "boss", "password": "s3cret"}).status_code == 200
    assert secured.delete(f"/api/admin/mechanics/{m['id']}").json() == {"deleted": True}
    assert secured.delete(f"/api/admin/mechanics/{m['id']}").status_code == 404
    names = [x["full_name"] for x in secured.get("/api/auth/mechanics").json()["items"]]
    assert "Кузнецов Олег" not in names
