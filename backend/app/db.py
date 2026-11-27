"""Соединение с базой приложения для парка машин, механиков и настроек подключений.

Чат, заявки и журнал ведёт Store (store.py) в том же файле SQLite. Парк машин нужен и там, где
Store нет (правила, инструменты агента, сводка парка), поэтому у этих модулей своё соединение.
"""
from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Iterator

from .config import get_settings


def now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


SETTINGS_SCHEMA = """
CREATE TABLE IF NOT EXISTS app_settings (
    key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL
);
"""


class Database:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(path), check_same_thread=False, timeout=10)
        self._db.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        self._ready: set[str] = set()
        self.ensure("settings", SETTINGS_SCHEMA)

    def ensure(self, name: str, schema: str) -> bool:
        """Создаёт таблицы модуля один раз за работу сервера. True — вызов первый, можно наполнить данными."""
        with self.lock:
            if name in self._ready:
                return False
            self._db.executescript(schema)
            self._db.commit()
            self._ready.add(name)
            return True

    def exec(self, sql: str, args: tuple = ()) -> sqlite3.Cursor:
        with self.lock:
            cur = self._db.execute(sql, args)
            self._db.commit()
            return cur

    def all(self, sql: str, args: tuple = ()) -> list[sqlite3.Row]:
        with self.lock:
            return self._db.execute(sql, args).fetchall()

    def one(self, sql: str, args: tuple = ()) -> sqlite3.Row | None:
        with self.lock:
            return self._db.execute(sql, args).fetchone()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Несколько записей одним действием: или все, или ни одной."""
        with self.lock:
            try:
                yield self._db
                self._db.commit()
            except BaseException:
                self._db.rollback()
                raise

    # --- служебные значения: настройки подключений, ключ подписи сессий, отметки наполнения ---
    def get_value(self, key: str) -> str | None:
        row = self.one("SELECT value FROM app_settings WHERE key=?", (key,))
        return row["value"] if row else None

    def set_value(self, key: str, value: str | None) -> None:
        if value is None:
            self.exec("DELETE FROM app_settings WHERE key=?", (key,))
        else:
            self.exec("INSERT OR REPLACE INTO app_settings (key, value, updated_at) VALUES (?,?,?)", (key, value, now()))

    def values(self, prefix: str) -> dict[str, str]:
        rows = self.all("SELECT key, value FROM app_settings WHERE key LIKE ?", (prefix + "%",))
        return {r["key"][len(prefix):]: r["value"] for r in rows}


@lru_cache
def _open(path: str) -> Database:
    return Database(Path(path))


def get_db() -> Database:
    """База текущего окружения. В тестах у каждого теста своя папка данных и своя база."""
    return _open(str(get_settings().db_path))
