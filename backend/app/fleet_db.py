"""Парк машин и проверки в базе приложения.

При первом запуске база наполняется из vehicles.json (материалы заказчика), если файл есть.
Дальше машины заводит и правит учётная система парка через /api/v1/vehicles, а новые проверки
присылает «НейроДВС» веб-хуком /api/v1/checks. Повторный запуск с тем же файлом добавляет только
то, чего в базе ещё нет: правки учётной системы не перетираются.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

from .db import Database, now

log = logging.getLogger("mechanic")

SCHEMA = """
CREATE TABLE IF NOT EXISTS vehicles (
    vehicle_id TEXT PRIMARY KEY,
    garage_no TEXT NOT NULL DEFAULT '', make TEXT NOT NULL DEFAULT '', model TEXT,
    vehicle_type TEXT NOT NULL DEFAULT '', engine_model TEXT NOT NULL, fuel TEXT NOT NULL DEFAULT '',
    active INTEGER NOT NULL DEFAULT 1, source TEXT NOT NULL,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS checks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    vehicle_id TEXT NOT NULL, session_id TEXT NOT NULL, checked_at TEXT NOT NULL,
    result TEXT, source TEXT NOT NULL, received_at TEXT NOT NULL,
    UNIQUE (vehicle_id, session_id)
);
CREATE INDEX IF NOT EXISTS checks_vehicle ON checks(vehicle_id);
"""

CARD_FIELDS = ("garage_no", "make", "model", "vehicle_type", "engine_model", "fuel")
# Поля результата проверки, как их отдаёт ML-сервис (раздел 5 ТЗ)
RESULT_FIELDS = ("status", "anomaly_type", "anomaly_title", "anomaly_score", "confidence",
                 "signal_quality", "description", "model_version")


def _moment(value: str) -> float:
    """Время проверки для сортировки. Время без пояса считается местным."""
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except (ValueError, OSError):
        return 0.0


def _session(row) -> dict:
    result = json.loads(row["result"]) if row["result"] else {}
    session = {"session_id": row["session_id"], "checked_at": row["checked_at"], "vehicle_id": row["vehicle_id"]}
    session.update({k: result.get(k) for k in RESULT_FIELDS})
    session.update({k: v for k, v in result.items() if k not in session})
    return session


class FleetDB:
    def __init__(self, db: Database):
        self.db = db
        db.ensure("fleet", SCHEMA)

    # --- наполнение из файла заказчика ---
    def seed_from_file(self, path: Path) -> int:
        """Добавляет машины и проверки из vehicles.json, которых в базе ещё нет. Возвращает, сколько машин добавлено."""
        if not path.exists():
            return 0
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            log.warning("Не удалось прочитать парк машин из %s: %s", path, exc)
            return 0
        added, stamp = 0, now()
        with self.db.transaction() as con:
            for v in data.get("vehicles", []):
                cur = con.execute(
                    "INSERT OR IGNORE INTO vehicles (vehicle_id, garage_no, make, model, vehicle_type, engine_model, fuel, "
                    "active, source, created_at, updated_at) VALUES (?,?,?,?,?,?,?,1,'file',?,?)",
                    (v["vehicle_id"], v.get("garage_no") or "", v.get("make") or "", v.get("model"),
                     v.get("vehicle_type") or "", v["engine_model"], v.get("fuel") or "", stamp, stamp),
                )
                added += cur.rowcount
                for s in v.get("sessions", []):
                    result = {k: val for k, val in s.items() if k not in ("session_id", "checked_at", "vehicle_id")}
                    con.execute(
                        "INSERT OR IGNORE INTO checks (vehicle_id, session_id, checked_at, result, source, received_at) "
                        "VALUES (?,?,?,?,'file',?)",
                        (v["vehicle_id"], s["session_id"], s["checked_at"], json.dumps(result, ensure_ascii=False), stamp),
                    )
        if added:
            log.info("Парк машин: из %s добавлено машин: %s", path.name, added)
        return added

    # --- чтение ---
    def __iter__(self):
        """Госномера машин в парке: перебор, как у прежнего словаря из файла."""
        return iter([r["vehicle_id"] for r in self.db.all("SELECT vehicle_id FROM vehicles WHERE active=1 ORDER BY vehicle_id")])

    def _sessions(self, vehicle_ids: list[str] | None = None) -> dict[str, list[dict]]:
        if vehicle_ids is None:
            rows = self.db.all("SELECT * FROM checks ORDER BY id")
        else:
            marks = ",".join("?" * len(vehicle_ids))
            rows = self.db.all(f"SELECT * FROM checks WHERE vehicle_id IN ({marks}) ORDER BY id", tuple(vehicle_ids))
        out: dict[str, list[dict]] = {}
        for r in sorted(rows, key=lambda r: (_moment(r["checked_at"]), r["id"])):
            out.setdefault(r["vehicle_id"], []).append(_session(r))
        return out

    @staticmethod
    def _card(row, sessions: list[dict]) -> dict:
        return {"vehicle_id": row["vehicle_id"], **{k: row[k] for k in CARD_FIELDS}, "sessions": sessions}

    def vehicle(self, vehicle_id: str, include_inactive: bool = False) -> dict | None:
        row = self.db.one("SELECT * FROM vehicles WHERE vehicle_id=?", (vehicle_id,))
        if row is None or (not row["active"] and not include_inactive):
            return None
        return self._card(row, self._sessions([vehicle_id]).get(vehicle_id, []))

    def vehicles(self, include_inactive: bool = False) -> list[dict]:
        sql = "SELECT * FROM vehicles" + ("" if include_inactive else " WHERE active=1") + " ORDER BY vehicle_id"
        rows = self.db.all(sql)
        sessions = self._sessions()
        return [self._card(r, sessions.get(r["vehicle_id"], [])) for r in rows]

    def record(self, vehicle_id: str) -> dict | None:
        """Карточка для учётной системы: поля, признак активности, сколько проверок и когда последняя."""
        row = self.db.one("SELECT * FROM vehicles WHERE vehicle_id=?", (vehicle_id,))
        return self._record(row, self._sessions([vehicle_id]).get(vehicle_id, [])) if row else None

    def records(self, include_inactive: bool = False) -> list[dict]:
        sql = "SELECT * FROM vehicles" + ("" if include_inactive else " WHERE active=1") + " ORDER BY vehicle_id"
        sessions = self._sessions()
        return [self._record(r, sessions.get(r["vehicle_id"], [])) for r in self.db.all(sql)]

    @staticmethod
    def _record(row, sessions: list[dict]) -> dict:
        return {
            "vehicle_id": row["vehicle_id"], **{k: row[k] for k in CARD_FIELDS},
            "active": bool(row["active"]), "checks_count": len(sessions),
            "last_check_at": sessions[-1]["checked_at"] if sessions else None,
            "created_at": row["created_at"], "updated_at": row["updated_at"],
        }

    # --- запись: учётная система парка ---
    def upsert(self, vehicle_id: str, fields: dict) -> bool:
        """Создаёт машину или обновляет переданные поля. Возвращает True, если машина новая.
        Создание и обновление по госномеру возвращают машину в парк, если её выводили."""
        stamp = now()
        with self.db.transaction() as con:
            exists = con.execute("SELECT 1 FROM vehicles WHERE vehicle_id=?", (vehicle_id,)).fetchone()
            if exists is None:
                card = {k: fields.get(k) for k in CARD_FIELDS}
                con.execute(
                    "INSERT INTO vehicles (vehicle_id, garage_no, make, model, vehicle_type, engine_model, fuel, active, "
                    "source, created_at, updated_at) VALUES (?,?,?,?,?,?,?,1,'api',?,?)",
                    (vehicle_id, card["garage_no"] or "", card["make"] or "", card["model"], card["vehicle_type"] or "",
                     card["engine_model"], card["fuel"] or "", stamp, stamp),
                )
                return True
            self._update(con, vehicle_id, {**fields, "active": True}, stamp)
            return False

    def update(self, vehicle_id: str, fields: dict) -> bool:
        """Меняет только переданные поля. False — такой машины нет."""
        with self.db.transaction() as con:
            if con.execute("SELECT 1 FROM vehicles WHERE vehicle_id=?", (vehicle_id,)).fetchone() is None:
                return False
            self._update(con, vehicle_id, fields, now())
            return True

    @staticmethod
    def _update(con, vehicle_id: str, fields: dict, stamp: str) -> None:
        sets, args = [], []
        for key in (*CARD_FIELDS, "active"):
            if key in fields:
                value = fields[key]
                if key == "active":
                    value = 1 if value else 0
                elif key != "model" and value is None:
                    value = ""
                sets.append(f"{key}=?")
                args.append(value)
        sets.append("updated_at=?")
        con.execute(f"UPDATE vehicles SET {', '.join(sets)} WHERE vehicle_id=?", (*args, stamp, vehicle_id))

    def deactivate(self, vehicle_id: str) -> bool:
        cur = self.db.exec("UPDATE vehicles SET active=0, updated_at=? WHERE vehicle_id=?", (now(), vehicle_id))
        return cur.rowcount > 0

    # --- запись: проверки от «НейроДВС» ---
    def add_check(self, vehicle_id: str, session_id: str, checked_at: str, result: dict | None) -> bool:
        """Новая проверка или повтор веб-хука. Повтор обновляет время и результат, если он передан.
        Возвращает True, если проверка новая."""
        stamp = now()
        payload = json.dumps(result, ensure_ascii=False) if result else None
        with self.db.transaction() as con:
            row = con.execute("SELECT id, result FROM checks WHERE vehicle_id=? AND session_id=?",
                              (vehicle_id, session_id)).fetchone()
            if row is None:
                con.execute(
                    "INSERT INTO checks (vehicle_id, session_id, checked_at, result, source, received_at) "
                    "VALUES (?,?,?,?,'api',?)",
                    (vehicle_id, session_id, checked_at, payload, stamp),
                )
                return True
            con.execute("UPDATE checks SET checked_at=?, result=COALESCE(?, result), received_at=? WHERE id=?",
                        (checked_at, payload, stamp, row["id"]))
            return False

    def check_meta(self, vehicle_id: str, session_id: str) -> dict | None:
        row = self.db.one("SELECT * FROM checks WHERE vehicle_id=? AND session_id=?", (vehicle_id, session_id))
        if row is None:
            return None
        return {"source": row["source"], "received_at": row["received_at"], "has_result": bool(row["result"]),
                "session": _session(row)}

    def fill_result(self, vehicle_id: str, session_id: str, result: dict) -> bool:
        """Результат проверки, полученный позже веб-хука (от ML-сервиса). Записывается, только если его ещё нет."""
        if not result.get("status"):
            return False
        payload = {k: result.get(k) for k in RESULT_FIELDS}
        cur = self.db.exec("UPDATE checks SET result=? WHERE vehicle_id=? AND session_id=? AND result IS NULL",
                           (json.dumps(payload, ensure_ascii=False), vehicle_id, session_id))
        return cur.rowcount > 0
