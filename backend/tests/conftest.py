"""Общая подготовка тестов: своя маленькая база знаний и подмена внешних сервисов.

Текст страниц в тестовой базе придуман для тестов и не взят из руководств заказчика.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

PAGES = {
    # Руководство двигателя ЯМЗ-236М2
    ("yamz236_rk", 10): (
        "Проверка давления масла. Давление масла в системе смазки прогретого двигателя должно быть не менее "
        "400 кПа при номинальной частоте вращения. Проверить давление масла контрольным манометром. "
        "При давлении ниже нормы снять и проверить масляный насос."
    ),
    ("yamz236_rk", 11): (
        "Регулировка клапанов. Тепловой зазор клапанов на холодном двигателе должен быть 0,25 мм. "
        "Проверить зазор щупом и отрегулировать клапанный механизм."
    ),
    ("yamz236_rk", 2): "\n".join(f"Раздел {i} . . . . . . . . . . . . {i * 3}" for i in range(1, 12))
    + "\nПроверка давления масла . . . . . . . . . . 10",
    # Две страницы одного двигателя, которые расходятся (П18)
    ("yamz236_re", 7): (
        "Замена масла в двигателе. Масло сливать сразу после остановки, пока двигатель горячий. "
        "Отвернуть пробку поддона и слить масло в чистую ёмкость."
    ),
    ("yamz236_rk", 12): (
        "Замена масла в двигателе. Масло сливать только на полностью остывшем двигателе. "
        "Отвернуть пробку поддона и слить масло."
    ),
    # Руководство другого двигателя
    ("zmz5234_rk", 5): (
        "Проверка давления масла. Давление масла в системе смазки должно быть не менее 250 кПа. "
        "Проверить давление масла манометром."
    ),
}


# Реестр подтверждённых расхождений для тестов: только документ, страница и слова-маркеры.
KNOWN_CONFLICTS = [{
    "id": "test-oil-drain", "topic": "На каком двигателе сливать масло",
    "keywords": [["слив", "масл"], ["замен", "масл"]],
    "statements": [
        {"manual_id": "yamz236_re", "pdf_page": 7, "markers": ["сливать", "горячий"]},
        {"manual_id": "yamz236_rk", "pdf_page": 12, "markers": ["сливать", "остывшем"]},
    ],
    "resolution": "Принято: сливать на остывшем двигателе.", "resolution_source": "тест",
}]


@pytest.fixture(autouse=True)
def environment(tmp_path, monkeypatch):
    monkeypatch.setenv("KB_DIR", str(tmp_path / "kb"))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("FLEET_DATA_PATH", str(ROOT / "mocks" / "data" / "vehicles.json"))
    monkeypatch.setenv("FAULT_TYPES_PATH", str(ROOT / "mocks" / "data" / "fault_types.json"))
    monkeypatch.setenv("MANUALS_CONFIG", str(ROOT / "config" / "manuals.json"))
    registry = tmp_path / "conflicts.json"
    registry.write_text(json.dumps(KNOWN_CONFLICTS, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setenv("CONFLICTS_CONFIG", str(registry))

    from app import config, conflicts, fleet, manuals
    from app.kb import index as kb_index

    caches = (config.get_settings, manuals.all_manuals, kb_index.get_index, fleet._load, fleet.fault_types,
              conflicts.known_conflicts)
    for cached in caches:
        cached.cache_clear()
    yield
    for cached in caches:
        cached.cache_clear()


@pytest.fixture
def index(environment):
    from app.kb.index import get_index
    from app.kb.ingest import chunk_page
    from app.kb.text import is_toc

    ix = get_index()
    for (manual_id, page), text in PAGES.items():
        ix.add_page(manual_id, page, text, False, [] if is_toc(text) else chunk_page(text))
    ix.commit()
    return ix


@pytest.fixture
def services(monkeypatch):
    """Подмена ML и ТОиР: ответы берутся из vehicles.json, как у заглушек заказчика."""
    from app import clients, fleet

    sent: list[dict] = []

    async def diagnose(vehicle_id: str, session_id: str) -> dict:
        vehicle = fleet.get_vehicle(vehicle_id)
        session = fleet.get_session(vehicle, session_id) if vehicle else None
        if session is None:
            raise clients.ServiceError("нет такой проверки", 404)
        return {k: v for k, v in session.items() if k != "checked_at"}

    async def create_ticket(payload: dict) -> dict:
        required = {"vehicle_id", "session_id", "anomaly_type", "conclusion", "urgency", "operations",
                    "spare_parts", "references"}
        assert set(payload) == required, "заявка собрана не по контракту"
        assert payload["operations"] and payload["references"] and payload["conclusion"]
        assert all(set(ref) == {"manual", "pdf_page"} for ref in payload["references"])
        sent.append(payload)
        return {"ticket_id": f"TKT-{len(sent):04d}", "status": "created"}

    monkeypatch.setattr(clients, "diagnose", diagnose)
    monkeypatch.setattr(clients, "create_ticket", create_ticket)
    return sent


def load_vehicles() -> list[dict]:
    return json.loads((ROOT / "mocks" / "data" / "vehicles.json").read_text(encoding="utf-8"))["vehicles"]


os.environ.setdefault("LLM_PROVIDER", "mock")
