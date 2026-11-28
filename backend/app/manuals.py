"""Реестр руководств: какой документ относится к какому двигателю.

Это единственное место, где задана связь «двигатель → документы». Поиск и ссылки
работают только по документам двигателя выбранной машины (правило П1).

Руководства заказчика перечислены в config/manuals.json. Администратор может загрузить новое
(library.py): оно хранится в базе приложения. Удалённое руководство заказчика отмечается в базе
и в реестр не попадает.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache

from .config import get_settings


@dataclass(frozen=True)
class Manual:
    id: str
    file: str
    designation: str
    title: str
    short: str
    year: int
    pages: int
    engines: tuple[str, ...]
    # base — из материалов заказчика (config/manuals.json), upload — загружено администратором
    source: str = "base"

    def public(self) -> dict:
        return {
            "manual_id": self.id,
            "designation": self.designation,
            "title": self.title,
            "short": self.short,
            "pages": self.pages,
        }


EXTRA_PREFIX = "manual.extra."   # загруженные администратором: JSON записи реестра
OFF_PREFIX = "manual.off."       # руководства заказчика, которые администратор удалил


def from_dict(m: dict, source: str = "base") -> Manual:
    return Manual(
        id=m["id"], file=m["file"], designation=m.get("designation", ""), title=m["title"],
        short=m["short"], year=int(m.get("year") or 0), pages=int(m["pages"]), engines=tuple(m["engines"]),
        source=source,
    )


@lru_cache
def all_manuals() -> tuple[Manual, ...]:
    raw = json.loads(get_settings().manuals_config.read_text(encoding="utf-8"))
    base = [from_dict(m) for m in raw]
    off: set[str] = set()
    extra: list[Manual] = []
    try:
        from .db import get_db

        db = get_db()
        off = set(db.values(OFF_PREFIX))
        extra = [from_dict(json.loads(v), "upload") for v in db.values(EXTRA_PREFIX).values()]
    except Exception:  # базы приложения ещё нет (сборка индекса из командной строки): только реестр заказчика
        pass
    return tuple([m for m in base if m.id not in off] + sorted(extra, key=lambda m: m.id))


def manual_by_id(manual_id: str) -> Manual | None:
    return next((m for m in all_manuals() if m.id == manual_id), None)


def manuals_for_engine(engine_model: str) -> list[Manual]:
    return [m for m in all_manuals() if engine_model in m.engines]


def manual_ids_for_engine(engine_model: str) -> list[str]:
    return [m.id for m in manuals_for_engine(engine_model)]
