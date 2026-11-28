"""Руководства в админке: администратор загружает PDF, индексирует его кнопкой и удаляет устаревшее.

PDF в Git не хранятся (просьба организаторов): на сервере они лежат в KB_DIR/pdf, рядом с индексом.
Новое руководство попадает в реестр (manuals.py) с двигателями, к которым относится: поиск и ссылки
по-прежнему идут только по документам двигателя машины (правило П1). Индексация одного руководства
идёт в фоне, ход виден в админке; остальные руководства в это время работают как обычно.
"""
from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator

import pymupdf

from . import demo, fleet, manuals
from .config import get_settings
from .db import get_db
from .kb import ingest
from .kb.index import get_index

MAX_BYTES = 300 * 1024 * 1024
# Ход индексации: id руководства → состояние. Хранится в памяти сервера: после перезапуска
# недоиндексированное руководство видно по числу страниц в индексе, его можно запустить заново
JOBS: dict[str, dict] = {}
_tasks: set[asyncio.Task] = set()


class LibraryError(ValueError):
    """Действие с руководством не выполнено: текст для администратора."""


class DemoLocked(LibraryError):
    """Действие запрещено на демо-стенде (demo.py)."""


def engines() -> list[str]:
    """Двигатели парка и уже известных руководств: из них администратор выбирает, к чему относится документ."""
    found: set[str] = set()
    try:
        found |= {r["engine_model"] for r in fleet.repo().db.all("SELECT DISTINCT engine_model FROM vehicles") if r["engine_model"]}
    except Exception:
        pass
    for m in manuals.all_manuals():
        found |= set(m.engines)
    return sorted(found)


def overview() -> dict:
    stats = get_index().manual_stats()
    pdf_dir = get_settings().pdf_dir
    items = []
    for m in manuals.all_manuals():
        s = stats.get(m.id, {"pages": 0, "ocr_pages": 0, "chunks": 0})
        job = JOBS.get(m.id)
        items.append({
            "manual_id": m.id, "short": m.short, "title": m.title, "designation": m.designation, "year": m.year or None,
            "engines": list(m.engines), "pages": m.pages, "source": m.source, "file": (pdf_dir / m.file).exists(),
            "indexed_pages": s["pages"], "ocr_pages": s["ocr_pages"], "chunks": s["chunks"],
            "job": job,
        })
    return {"manuals": items, "engines": engines(), "ocr": ingest.has_ocr()}


async def add(body: AsyncIterator[bytes], *, title: str, short: str, designation: str, year: int | None,
              engines: list[str]) -> manuals.Manual:
    """Сохраняет присланный PDF и запись реестра. Проверяет, что это PDF и у него есть страницы."""
    if not engines:
        raise LibraryError("Укажите хотя бы один двигатель: без этого агент не найдёт руководство для машины")
    if demo.enabled() and sum(m.source == "upload" for m in manuals.all_manuals()) >= demo.MAX_UPLOADS:
        raise DemoLocked(demo.locked(f"загружать больше {demo.MAX_UPLOADS} руководств"))
    if any(m.short.lower() == short.strip().lower() for m in manuals.all_manuals()):
        raise LibraryError(f"Руководство с коротким названием «{short.strip()}» уже есть")
    manual_id = "up_" + uuid.uuid4().hex[:10]
    pdf_dir = get_settings().pdf_dir
    pdf_dir.mkdir(parents=True, exist_ok=True)
    path = pdf_dir / f"{manual_id}.pdf"
    tmp = path.with_suffix(".part")
    size = 0
    try:
        with tmp.open("wb") as out:
            async for chunk in body:
                size += len(chunk)
                if size > MAX_BYTES:
                    raise LibraryError(f"Файл больше {MAX_BYTES // (1024 * 1024)} МБ")
                out.write(chunk)
        if size == 0:
            raise LibraryError("Файл пустой")
        with tmp.open("rb") as f:
            if f.read(5) != b"%PDF-":
                raise LibraryError("Это не PDF. Загрузите руководство в формате PDF")
        try:
            with pymupdf.open(tmp) as doc:
                pages = len(doc)
        except Exception as exc:
            raise LibraryError("PDF не открывается: файл повреждён или защищён паролем") from exc
        if pages == 0:
            raise LibraryError("В PDF нет страниц")
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)
    record = {"id": manual_id, "file": path.name, "designation": designation.strip(), "title": title.strip(),
              "short": short.strip(), "year": year or 0, "pages": pages, "engines": engines}
    get_db().set_value(manuals.EXTRA_PREFIX + manual_id, json.dumps(record, ensure_ascii=False))
    manuals.all_manuals.cache_clear()
    return manuals.manual_by_id(manual_id)


def start_index(manual_id: str) -> None:
    """Индексация одного руководства в фоне. Повторный запуск во время работы отклоняется."""
    manual = manuals.manual_by_id(manual_id)
    if manual is None:
        raise LibraryError("Нет такого руководства")
    if demo.enabled() and manual.source == "base":
        raise DemoLocked(demo.locked("переиндексировать руководства заказчика"))
    if not (get_settings().pdf_dir / manual.file).exists():
        raise LibraryError("Файла руководства нет на сервере: загрузите PDF заново")
    if JOBS.get(manual_id, {}).get("state") == "running":
        raise LibraryError("Индексация этого руководства уже идёт")
    JOBS[manual_id] = {"state": "running", "done": 0, "total": manual.pages, "error": None}

    def progress(done: int, total: int) -> None:
        JOBS[manual_id].update(done=done, total=total)

    async def run() -> None:
        try:
            result = await asyncio.to_thread(ingest.index_manual, manual, get_index(), ingest.has_ocr(), progress)
            JOBS[manual_id].update(state="done", done=result["pages"], total=result["pages"])
        except Exception as exc:  # ошибку видно в админке, сервер продолжает работать
            JOBS[manual_id].update(state="error", error=str(exc)[:300])

    task = asyncio.get_running_loop().create_task(run())
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


def remove(manual_id: str) -> None:
    """Убирает руководство из индекса и реестра. Загруженное администратором удаляется вместе с файлом,
    руководство заказчика отмечается удалённым (его PDF остаётся в материалах заказчика)."""
    manual = manuals.manual_by_id(manual_id)
    if manual is None:
        raise LibraryError("Нет такого руководства")
    if demo.enabled() and manual.source == "base":
        raise DemoLocked(demo.locked("удалять руководства заказчика"))
    if JOBS.get(manual_id, {}).get("state") == "running":
        raise LibraryError("Идёт индексация этого руководства: дождитесь окончания")
    get_index().remove_manual(manual_id)
    db = get_db()
    if manual.source == "upload":
        db.set_value(manuals.EXTRA_PREFIX + manual_id, None)
        (get_settings().pdf_dir / manual.file).unlink(missing_ok=True)
    else:
        db.set_value(manuals.OFF_PREFIX + manual_id, "1")
    JOBS.pop(manual_id, None)
    manuals.all_manuals.cache_clear()
