"""MCP-коннектор: инструменты, дневной лимит, доступ по ключу. Сервер агента подменён."""

import json

import httpx
import pytest
from mcp import Client
from starlette.testclient import TestClient

import connector

FLEET = {
    "summary": {"total": 2, "ok": 1, "attention": 0, "quarantine": 1, "recheck": 0},
    "vehicles": [
        {"vehicle_id": "A101TT77", "garage_no": "Г-1", "title": "МАЗ-5337", "vehicle_type": "грузовой",
         "engine_model": "ЯМЗ-236М2", "fleet_status": "quarantine", "priority": "high", "needs_recheck": False,
         "sessions_count": 2, "tickets": [],
         "last_session": {"session_id": "S-9003", "status": "anomaly", "anomaly_type": "F02",
                          "anomaly_title": "Низкое давление масла", "anomaly_score": 0.81, "confidence": 0.86,
                          "signal_quality": "good", "checked_at": "2026-11-20T10:00:00+03:00"}},
        {"vehicle_id": "B202TT77", "garage_no": "Г-2", "title": "ПАЗ-3205", "vehicle_type": "автобус",
         "engine_model": "ЗМЗ-5234.10", "fleet_status": "ok", "priority": None, "needs_recheck": False,
         "sessions_count": 1, "tickets": [], "last_session": None},
    ],
}

AGENT = {
    "message_id": "m_1", "vehicle_id": "A101TT77", "session_id": "S-9003", "kind": "verdict",
    "text": "Низкое давление масла: на дефектовку до выпуска в рейс",
    "diagnosis": {"status": "anomaly"}, "assessment": {"priority": "high", "ticket_allowed": True},
    "answer": {"checks": [{"text": "Проверить давление", "refs": [{"manual_id": "yamz236_rk", "pdf_page": 10}]}]},
    "draft": None, "ticket": None,
    "steps": [{"tool": "get_diagnosis", "title": "Получаю результат проверки", "detail": "x" * 1000, "data": {"a": 1}}],
    "usage": {"input_tokens": 100, "output_tokens": 20, "cost_rub": 1.5, "duration_ms": 12000, "extra": 1},
}


@pytest.fixture
def calls(monkeypatch):
    """Подменённый сервер агента: запоминает запросы, отвечает образцами."""
    seen: list[tuple[str, str, dict | None, str | None]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        seen.append((request.method, request.url.path, body, request.headers.get("x-api-key")))
        path = request.url.path
        if path == "/api/fleet":
            return httpx.Response(200, json=FLEET)
        if path == "/api/vehicles/A101TT77":
            return httpx.Response(200, json={**FLEET["vehicles"][0], "sessions": [FLEET["vehicles"][0]["last_session"]],
                                             "manuals": [{"manual_id": "yamz236_rk", "short": "РК", "title": "Ремонт",
                                                          "pages": 287, "designation": "лишнее"}],
                                             "trend": None})
        if path == "/api/manuals/yamz236_rk/pages/10":
            return httpx.Response(200, json={"manual_id": "yamz236_rk", "short": "РК", "title": "Ремонт", "engine": "ЯМЗ",
                                             "page": 10, "page_count": 287, "text": "Давление масла 400 кПа"})
        if path.startswith("/api/v1/agent/"):
            return httpx.Response(200, json=AGENT)
        return httpx.Response(404, json={"detail": "Машина не найдена"})

    monkeypatch.setenv("MCP_BACKEND_KEY", "backend-secret")
    monkeypatch.setattr(connector, "_transport", lambda: httpx.MockTransport(handler))
    monkeypatch.setattr(connector, "quota", connector.Quota())
    return seen


def payload(result) -> dict:
    assert not result.is_error, result.content
    if result.structured_content is not None:
        data = result.structured_content
        return data.get("result", data) if set(data) == {"result"} else data
    return json.loads(result.content[0].text)


async def test_tools_listed_with_prompt():
    async with Client(connector.server) as client:
        tools = {t.name for t in (await client.list_tools()).tools}
        prompts = {p.name for p in (await client.list_prompts()).prompts}
    assert tools == {"fleet_overview", "vehicle_details", "diagnose", "ask_agent", "confirm_ticket",
                     "read_manual_page", "connector_status"}
    assert "evaluate_digital_mechanic" in prompts


async def test_fleet_filter_and_backend_key(calls):
    async with Client(connector.server) as client:
        data = payload(await client.call_tool("fleet_overview", {"status": "quarantine"}))
    assert [v["vehicle_id"] for v in data["vehicles"]] == ["A101TT77"]
    assert data["vehicles"][0]["last_check"]["session_id"] == "S-9003"
    assert calls[0][3] == "backend-secret"


async def test_vehicle_details_keeps_manuals_short(calls):
    async with Client(connector.server) as client:
        data = payload(await client.call_tool("vehicle_details", {"vehicle_id": " A101TT77 "}))
    assert data["manuals"] == [{"manual_id": "yamz236_rk", "short": "РК", "title": "Ремонт", "pages": 287}]
    assert data["checks"][0]["status"] == "anomaly"


async def test_diagnose_signed_and_compacted(calls):
    async with Client(connector.server) as client:
        data = payload(await client.call_tool("diagnose", {"vehicle_id": "A101TT77"}))
    method, path, body, _ = calls[-1]
    assert (method, path) == ("POST", "/api/v1/agent/diagnose")
    assert body["mechanic"] == connector.MECHANIC and body["level"] == "expert"
    assert data["kind"] == "verdict" and data["answer"]["checks"][0]["refs"][0]["pdf_page"] == 10
    step = data["agent_steps"][0]
    assert "data" not in step and len(step["detail"]) <= 301
    assert "extra" not in data["usage"]


async def test_ask_and_confirm_go_to_agent(calls):
    async with Client(connector.server) as client:
        payload(await client.call_tool("ask_agent", {"vehicle_id": "A101TT77", "question": "Создай заявку"}))
        payload(await client.call_tool("confirm_ticket", {"draft_id": "d_5", "warning_ack": True}))
    assert calls[-2][1] == "/api/v1/agent/ask" and calls[-2][2]["text"] == "Создай заявку"
    assert calls[-1][1] == "/api/v1/agent/confirm" and calls[-1][2]["warning_ack"] is True


async def test_manual_page(calls):
    async with Client(connector.server) as client:
        data = payload(await client.call_tool("read_manual_page", {"manual_id": "yamz236_rk", "page": 10}))
    assert data["text"] == "Давление масла 400 кПа" and data["page"] == 10


async def test_backend_error_is_readable(calls):
    async with Client(connector.server) as client:
        result = await client.call_tool("vehicle_details", {"vehicle_id": "X000XX00"})
    assert result.is_error
    assert "Машина не найдена" in result.content[0].text and "404" in result.content[0].text


async def test_daily_limit(calls, monkeypatch):
    monkeypatch.setenv("MCP_DAILY_LIMIT", "1")
    async with Client(connector.server) as client:
        payload(await client.call_tool("diagnose", {"vehicle_id": "A101TT77"}))
        second = await client.call_tool("ask_agent", {"vehicle_id": "A101TT77", "question": "Давление масла?"})
        free = payload(await client.call_tool("fleet_overview", {}))
    assert second.is_error and "лимит" in second.content[0].text
    assert free["summary"]["total"] == 2  # чтение без лимита
    assert sum(1 for c in calls if c[1].startswith("/api/v1/agent/")) == 1


def test_http_access(monkeypatch):
    """Один запуск приложения: менеджер сессий MCP стартует один раз на процесс, как в работе сервиса."""
    init = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                       "clientInfo": {"name": "test", "version": "1"}}}
    headers = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json",
               "Host": "digital-mechanic.ru"}
    with TestClient(connector.app) as http:
        assert http.get("/health").json()["status"] == "ok"
        # Без ключей на сервере коннектор закрыт
        monkeypatch.delenv("MCP_ACCESS_KEYS", raising=False)
        assert http.post("/mcp/anything", json=init, headers=headers).status_code == 503
        monkeypatch.setenv("MCP_ACCESS_KEYS", "jury-key,second")
        assert http.post("/mcp/wrong", json=init, headers=headers).status_code == 403
        assert http.post("/mcp", json=init, headers=headers).status_code == 403
        assert http.post("/other", json=init, headers=headers).status_code == 404
        ok = http.post("/mcp/jury-key", json=init, headers=headers)
        assert ok.status_code == 200, ok.text
        assert "digital-mechanic" in ok.text
        bearer = http.post("/mcp", json=init, headers={**headers, "Authorization": "Bearer second"})
        assert bearer.status_code == 200, bearer.text
