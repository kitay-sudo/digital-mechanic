"""Механики: заводит администратор (экран «Механики» или /api/v1/mechanics).

У механика ФИО, возраст, размер шрифта и подача ответов (применяются после входа), PIN из четырёх
цифр и признак «работает». PIN хранится только хэшем с солью (PBKDF2-SHA256). После пяти неверных
PIN подряд вход этого механика закрыт на минуту.
"""
from __future__ import annotations

import functools
import hashlib
import hmac
import logging
import os
import re
import secrets
import time

from .db import Database, get_db, now

log = logging.getLogger("mechanic")

SCHEMA = """
CREATE TABLE IF NOT EXISTS mechanics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    full_name TEXT NOT NULL, age INTEGER,
    font_size TEXT NOT NULL DEFAULT 'normal', level TEXT NOT NULL DEFAULT 'expert',
    pin_hash TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1,
    failed INTEGER NOT NULL DEFAULT 0, locked_until REAL NOT NULL DEFAULT 0,
    version INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
"""

MAX_FAILS = 5
LOCK_SECONDS = 60
ITERATIONS = 100_000
FONT_SIZES = ("normal", "large")
LEVELS = ("expert", "novice")
PIN_RE = re.compile(r"^\d{4}$")

DEMO = (
    {"full_name": "Иванов Иван", "age": 54, "level": "expert", "font_size": "normal", "pin": "1111"},
    {"full_name": "Петров Пётр", "age": 41, "level": "expert", "font_size": "normal", "pin": "2222"},
    {"full_name": "Сидоров Сергей", "age": 23, "level": "novice", "font_size": "large", "pin": "3333"},
)


def hash_pin(pin: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", pin.encode(), salt, ITERATIONS)
    return f"pbkdf2_sha256${ITERATIONS}${salt.hex()}${digest.hex()}"


@functools.lru_cache(maxsize=64)
def _demo_match(pin: str, stored: str) -> bool:
    return check_pin(pin, stored)


def check_pin(pin: str, stored: str) -> bool:
    try:
        _, rounds, salt, digest = stored.split("$")
        actual = hashlib.pbkdf2_hmac("sha256", pin.encode(), bytes.fromhex(salt), int(rounds))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual.hex(), digest)


def clean_name(name: str) -> str:
    return re.sub(r"\s+", " ", name).strip()


class MechanicError(Exception):
    """Ошибка с текстом для администратора или механика. status — код ответа HTTP."""

    def __init__(self, message: str, status: int = 400, **extra):
        super().__init__(message)
        self.status = status
        self.extra = extra


class Mechanics:
    def __init__(self, db: Database):
        self.db = db
        if db.ensure("mechanics", SCHEMA) and os.environ.get("DEMO_SEED", "").strip() in ("1", "true", "yes"):
            self.seed_demo()

    def seed_demo(self) -> int:
        """Демо-наполнение (DEMO_SEED=1): трое механиков, если список пуст."""
        if self.db.one("SELECT 1 FROM mechanics LIMIT 1"):
            return 0
        for m in DEMO:
            self.create(m)
        log.info("Механики: добавлено демо-наполнение (%s)", ", ".join(m["full_name"] for m in DEMO))
        return len(DEMO)

    # --- чтение ---
    @staticmethod
    def public(row) -> dict:
        return {
            "id": row["id"], "full_name": row["full_name"], "age": row["age"],
            "font_size": row["font_size"], "level": row["level"], "active": bool(row["active"]),
            "created_at": row["created_at"], "updated_at": row["updated_at"],
        }

    def list(self, include_inactive: bool = True) -> list[dict]:
        sql = "SELECT * FROM mechanics" + ("" if include_inactive else " WHERE active=1")
        rows = self.db.all(sql + " ORDER BY full_name COLLATE NOCASE, id")
        return sorted((self.public(r) for r in rows), key=lambda m: (m["full_name"].lower(), m["id"]))

    def get(self, mechanic_id: int) -> dict | None:
        row = self.db.one("SELECT * FROM mechanics WHERE id=?", (mechanic_id,))
        return self.public(row) if row else None

    def demo_pins(self) -> dict[int, str]:
        """PIN демо-механиков для экрана входа на демонстрационном стенде (DEMO_SEED=1).
        Только пока PIN не сменили: сверка по хэшу, результат запоминается по самому хэшу."""
        if os.environ.get("DEMO_SEED", "").strip() not in ("1", "true", "yes"):
            return {}
        known = {m["full_name"]: m["pin"] for m in DEMO}
        out = {}
        for row in self.db.all("SELECT id, full_name, pin_hash FROM mechanics WHERE active=1"):
            pin = known.get(row["full_name"])
            if pin and _demo_match(pin, row["pin_hash"]):
                out[row["id"]] = pin
        return out

    def session_version(self, mechanic_id: int) -> int | None:
        """Версия входа: меняется при смене PIN и отключении, старые сессии механика перестают действовать."""
        row = self.db.one("SELECT version, active FROM mechanics WHERE id=?", (mechanic_id,))
        return row["version"] if row and row["active"] else None

    # --- запись ---
    def _check(self, data: dict, current_id: int | None = None) -> dict:
        out = {}
        if "full_name" in data:
            name = clean_name(str(data["full_name"] or ""))
            if len(name) < 2:
                raise MechanicError("Укажите ФИО механика", 422, field="full_name")
            if len(name) > 80:
                raise MechanicError("ФИО длиннее 80 знаков", 422, field="full_name")
            # Сравнение без учёта регистра в Python: lower() в SQLite не знает кириллицу
            twin = next((r for r in self.db.all("SELECT id, full_name FROM mechanics")
                         if r["full_name"].lower() == name.lower() and r["id"] != current_id), None)
            if twin is not None:
                raise MechanicError(f"Механик «{name}» уже есть в списке. Добавьте отчество или инициал, чтобы их различать.",
                                    409, field="full_name")
            out["full_name"] = name
        if "age" in data:
            age = data["age"]
            if age is not None and (not isinstance(age, int) or not 16 <= age <= 90):
                raise MechanicError("Возраст — целое число от 16 до 90", 422, field="age")
            out["age"] = age
        if "font_size" in data:
            if data["font_size"] not in FONT_SIZES:
                raise MechanicError("Размер шрифта: normal (обычный) или large (крупный)", 422, field="font_size")
            out["font_size"] = data["font_size"]
        if "level" in data:
            if data["level"] not in LEVELS:
                raise MechanicError("Подача: expert (опытный) или novice (новичок)", 422, field="level")
            out["level"] = data["level"]
        if "pin" in data and data["pin"] is not None:
            pin = str(data["pin"])
            if not PIN_RE.match(pin):
                raise MechanicError("PIN — ровно 4 цифры", 422, field="pin")
            out["pin_hash"] = hash_pin(pin)
        if "active" in data and data["active"] is not None:
            out["active"] = 1 if data["active"] else 0
        return out

    def create(self, data: dict) -> dict:
        if not data.get("full_name"):
            raise MechanicError("Укажите ФИО механика", 422, field="full_name")
        if not data.get("pin"):
            raise MechanicError("Задайте PIN из 4 цифр", 422, field="pin")
        fields = self._check({"font_size": "normal", "level": "expert", "age": None, **data})
        stamp = now()
        cur = self.db.exec(
            "INSERT INTO mechanics (full_name, age, font_size, level, pin_hash, active, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (fields["full_name"], fields["age"], fields["font_size"], fields["level"], fields["pin_hash"],
             fields.get("active", 1), stamp, stamp),
        )
        return self.get(cur.lastrowid)

    def update(self, mechanic_id: int, data: dict) -> dict:
        if self.get(mechanic_id) is None:
            raise MechanicError("Механик не найден", 404)
        fields = self._check(data, mechanic_id)
        if not fields:
            return self.get(mechanic_id)
        sets = [f"{k}=?" for k in fields]
        args = list(fields.values())
        if "pin_hash" in fields or fields.get("active") == 0:
            # Новый PIN или отключение: прежний вход механика больше не действует, блокировка снимается
            sets += ["version=version+1", "failed=0", "locked_until=0"]
        sets.append("updated_at=?")
        self.db.exec(f"UPDATE mechanics SET {', '.join(sets)} WHERE id=?", (*args, now(), mechanic_id))
        return self.get(mechanic_id)

    def deactivate(self, mechanic_id: int) -> dict:
        return self.update(mechanic_id, {"active": False})

    def delete(self, mechanic_id: int) -> None:
        """Удаляет механика насовсем: вход пропадает сразу. Подписи в чате и журнале остаются текстом."""
        if self.get(mechanic_id) is None:
            raise MechanicError("Механик не найден", 404)
        self.db.exec("DELETE FROM mechanics WHERE id=?", (mechanic_id,))

    # --- вход по PIN ---
    def login(self, mechanic_id: int, pin: str, clock=time.time) -> dict:
        """Проверяет PIN. Неверный PIN — MechanicError 401 с числом оставшихся попыток,
        пятая ошибка подряд закрывает вход на минуту (429)."""
        row = self.db.one("SELECT * FROM mechanics WHERE id=?", (mechanic_id,))
        if row is None or not row["active"]:
            raise MechanicError("Механика нет в списке. Выберите себя ещё раз или обратитесь к администратору.", 404)
        moment = clock()
        if row["locked_until"] > moment:
            wait = int(row["locked_until"] - moment + 0.999)
            raise MechanicError(f"Слишком много неверных PIN. Подождите {wait} с и попробуйте снова.", 429, retry_after=wait)
        if check_pin(str(pin), row["pin_hash"]):
            self.db.exec("UPDATE mechanics SET failed=0, locked_until=0 WHERE id=?", (mechanic_id,))
            return {**self.public(row), "version": row["version"]}
        failed = row["failed"] + 1
        if failed >= MAX_FAILS:
            self.db.exec("UPDATE mechanics SET failed=0, locked_until=? WHERE id=?", (moment + LOCK_SECONDS, mechanic_id))
            raise MechanicError(f"Неверный PIN {MAX_FAILS} раз подряд. Вход закрыт на минуту, потом попробуйте снова.",
                                429, retry_after=LOCK_SECONDS)
        self.db.exec("UPDATE mechanics SET failed=? WHERE id=?", (failed, mechanic_id))
        left = MAX_FAILS - failed
        raise MechanicError(f"Неверный PIN. Осталось попыток: {left}.", 401, attempts_left=left)


def repo() -> Mechanics:
    return Mechanics(get_db())
