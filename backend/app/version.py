"""Версия продукта: одна на сервер, из pyproject.toml. Видна в /api/health и в документации API."""
from __future__ import annotations

import tomllib
from pathlib import Path


def _read() -> str:
    try:
        data = tomllib.loads((Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(encoding="utf-8"))
        return str(data["project"]["version"])
    except (OSError, KeyError, tomllib.TOMLDecodeError):
        return "неизвестна"


VERSION = _read()
