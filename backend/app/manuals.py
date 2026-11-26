"""Реестр руководств: какой документ относится к какому двигателю.

Это единственное место, где задана связь «двигатель → документы». Поиск и ссылки
работают только по документам двигателя выбранной машины (правило П1).
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

    def public(self) -> dict:
        return {
            "manual_id": self.id,
            "designation": self.designation,
            "title": self.title,
            "short": self.short,
            "pages": self.pages,
        }


@lru_cache
def all_manuals() -> tuple[Manual, ...]:
    raw = json.loads(get_settings().manuals_config.read_text(encoding="utf-8"))
    return tuple(
        Manual(
            id=m["id"], file=m["file"], designation=m["designation"], title=m["title"],
            short=m["short"], year=m["year"], pages=m["pages"], engines=tuple(m["engines"]),
        )
        for m in raw
    )


def manual_by_id(manual_id: str) -> Manual | None:
    return next((m for m in all_manuals() if m.id == manual_id), None)


def manuals_for_engine(engine_model: str) -> list[Manual]:
    return [m for m in all_manuals() if engine_model in m.engines]


def manual_ids_for_engine(engine_model: str) -> list[str]:
    return [m.id for m in manuals_for_engine(engine_model)]
