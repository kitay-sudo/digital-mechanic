"""Демо-стенд (DEMO_STAND=1): доступ для экспертов на экране входа и защита от поломок."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import manuals, mechanics


@pytest.fixture
def stand(index, monkeypatch):
    monkeypatch.setenv("DEMO_STAND", "1")
    monkeypatch.setenv("DEMO_SEED", "1")
    monkeypatch.setenv("ADMIN_LOGIN", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "demo-pass-123")
    from app.main import app

    with TestClient(app) as client:
        yield client


def test_experts_see_admin_access(stand):
    me = stand.get("/api/auth/me").json()
    assert me["demo"] is True and me["demo_admin"] == {"login": "admin", "password": "demo-pass-123"}


def test_customer_manual_and_settings_are_locked(stand):
    r = stand.delete("/api/admin/manuals/yamz236_rk")
    assert r.status_code == 403 and r.json()["detail"].startswith("На демо-стенде")
    assert manuals.manual_by_id("yamz236_rk") is not None
    r = stand.post("/api/admin/manuals/yamz236_rk/index")
    assert r.status_code == 403
    r = stand.put("/api/admin/integrations", json={"llm_mode": "local", "llm_local_url": "http://x:1/v1", "llm_local_model": "m"})
    assert r.status_code == 403 and r.json()["detail"].startswith("На демо-стенде")


def test_demo_mechanics_locked_own_mechanic_editable(stand):
    repo = mechanics.repo()
    demo_id = next(iter(repo.demo_pins()))
    r = stand.put(f"/api/admin/mechanics/{demo_id}", json={"pin": "9999"})
    assert r.status_code == 403 and r.json()["detail"].startswith("На демо-стенде")
    assert stand.delete(f"/api/admin/mechanics/{demo_id}").status_code == 403
    created = stand.post("/api/admin/mechanics", json={"full_name": "Эксперт Проверяющий", "pin": "4321"})
    assert created.status_code == 201, created.text
    own = created.json()["id"]
    assert stand.put(f"/api/admin/mechanics/{own}", json={"level": "novice"}).status_code == 200
    assert stand.delete(f"/api/admin/mechanics/{own}").status_code == 200


def test_without_flag_nothing_is_locked(index, monkeypatch):
    monkeypatch.delenv("DEMO_STAND", raising=False)
    from app.main import app

    with TestClient(app) as client:
        me = client.get("/api/auth/me").json()
        assert me["demo"] is False and me["demo_admin"] is None
        assert client.delete("/api/admin/manuals/yamz236_rk").status_code == 200
