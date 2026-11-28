"""Материалы при запуске сервера: руководства, положенные вручную после первого запуска, попадают в индекс."""
from __future__ import annotations

import pymupdf

from app import materials
from app.config import get_settings
from app.kb import ingest
from app.kb.index import get_index


def test_pdf_added_after_empty_start_is_indexed(monkeypatch):
    settings = get_settings()
    monkeypatch.delenv("MATERIALS_URL", raising=False)

    # Первый запуск без материалов: индекс собрался пустым
    get_index().commit()
    assert settings.index_path.exists() and materials.unindexed() == []

    # PDF положили вручную
    settings.pdf_dir.mkdir(parents=True, exist_ok=True)
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), "Проверка давления масла")
    doc.save(settings.pdf_dir / "yamz-236_re_2010.pdf")
    assert materials.unindexed() == ["yamz-236_re_2010.pdf"]
    assert materials.INDEX in materials.absent()

    built: list[bool] = []
    monkeypatch.setattr(ingest, "main", lambda: built.append(True) or 0)
    assert materials.main(["--if-missing"]) == 0
    assert built == [True]
