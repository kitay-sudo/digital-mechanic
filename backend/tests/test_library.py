"""Руководства в админке: загрузка PDF, индексация кнопкой, удаление."""
from __future__ import annotations

import time

import pymupdf
import pytest
from fastapi.testclient import TestClient

from app import manuals
from app.config import get_settings
from app.kb.index import get_index


def _pdf(text: str, pages: int = 3) -> bytes:
    doc = pymupdf.open()
    for n in range(pages):
        page = doc.new_page()
        page.insert_text((72, 90), f"{text} page {n + 1}", fontsize=12)
        page.insert_text((72, 120), "Oil pressure on a warm engine must be 400-700 kPa at rated speed.", fontsize=11)
    data = doc.tobytes()
    doc.close()
    return data


@pytest.fixture
def client(index):
    from app.main import app

    with TestClient(app) as c:
        yield c


def _wait_done(client, manual_id: str) -> dict:
    for _ in range(100):
        item = next(m for m in client.get("/api/admin/manuals").json()["manuals"] if m["manual_id"] == manual_id)
        if item["job"] and item["job"]["state"] != "running":
            return item
        time.sleep(0.05)
    raise AssertionError("индексация не закончилась")


def test_upload_index_search_and_delete(client):
    body = _pdf("Zzqxval maintenance manual")
    r = client.put("/api/admin/manuals/upload", params={"title": "Test engine service manual", "short": "TST-1",
                                                        "engines": "ЯМЗ-236М2", "year": 2026},
                   content=body, headers={"Content-Type": "application/pdf"})
    assert r.status_code == 200, r.text
    manual_id = r.json()["added"]
    item = _wait_done(client, manual_id)
    assert item["job"]["state"] == "done" and item["indexed_pages"] == 3 and item["chunks"] > 0
    assert item["source"] == "upload" and item["pages"] == 3 and item["engines"] == ["ЯМЗ-236М2"]
    # Новое руководство сразу в реестре двигателя и в поиске (правило П1 действует и для него)
    assert manual_id in manuals.manual_ids_for_engine("ЯМЗ-236М2")
    assert manual_id not in manuals.manual_ids_for_engine("ЯМЗ-536")
    assert get_index().search("zzqxval", [manual_id])
    # Повторная индексация кнопкой тоже работает, а удаление убирает и индекс, и файл
    assert client.post(f"/api/admin/manuals/{manual_id}/index").status_code == 200
    _wait_done(client, manual_id)
    path = get_settings().pdf_dir / f"{manual_id}.pdf"
    assert path.exists()
    assert client.delete(f"/api/admin/manuals/{manual_id}").status_code == 200
    assert manuals.manual_by_id(manual_id) is None and not path.exists()
    assert not get_index().search("zzqxval", [manual_id])


def test_upload_rejects_bad_files(client):
    put = lambda content, **params: client.put(  # noqa: E731
        "/api/admin/manuals/upload", content=content, headers={"Content-Type": "application/pdf"},
        params={"title": "Bad file manual", "short": "BAD-1", "engines": "ЯМЗ-536", **params})
    not_pdf = put(b"hello, this is not a pdf")
    assert not_pdf.status_code == 422 and "не PDF" in not_pdf.json()["detail"]
    assert put(b"").status_code == 422
    no_engine = put(_pdf("x"), engines=" , ")
    assert no_engine.status_code == 422 and "двигатель" in no_engine.json()["detail"]
    taken = put(_pdf("x"), short="РЭ ЯМЗ-236М2")
    assert taken.status_code == 422 and "уже есть" in taken.json()["detail"]
    assert not list(get_settings().pdf_dir.glob("up_*")) if get_settings().pdf_dir.exists() else True


def test_delete_customer_manual_hides_it(client):
    assert "yamz236_rk" in manuals.manual_ids_for_engine("ЯМЗ-236М2")
    r = client.delete("/api/admin/manuals/yamz236_rk")
    assert r.status_code == 200
    assert "yamz236_rk" not in manuals.manual_ids_for_engine("ЯМЗ-236М2")
    assert not get_index().search("сливать", ["yamz236_rk"])
    assert client.delete("/api/admin/manuals/yamz236_rk").status_code == 404
