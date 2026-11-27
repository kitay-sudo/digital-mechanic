"""Хранилище приложения в SQLite: чат, разборы проверок, черновики, заявки, журнал модели.

Заглушка ТОиР заявки не хранит и список не отдаёт, поэтому историю заявок по машине
приложение ведёт само (K7). Журнал вызовов модели нужен для расчёта стоимости сценария.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

from . import alerts, journal

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    vehicle_id TEXT NOT NULL, session_id TEXT, role TEXT NOT NULL,
    payload TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS messages_vehicle ON messages(vehicle_id, id);
CREATE TABLE IF NOT EXISTS analyses (
    vehicle_id TEXT NOT NULL, session_id TEXT NOT NULL,
    diagnosis TEXT NOT NULL, assessment TEXT NOT NULL, created_at TEXT NOT NULL,
    PRIMARY KEY (vehicle_id, session_id)
);
CREATE TABLE IF NOT EXISTS drafts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    vehicle_id TEXT NOT NULL, session_id TEXT NOT NULL,
    payload TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tickets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id TEXT NOT NULL, vehicle_id TEXT NOT NULL, session_id TEXT NOT NULL,
    payload TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS tickets_vehicle ON tickets(vehicle_id);
CREATE TABLE IF NOT EXISTS turns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    vehicle_id TEXT NOT NULL, session_id TEXT, scenario_id INTEGER,
    kind TEXT, duration_ms INTEGER, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS stt_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    model TEXT NOT NULL, seconds REAL NOT NULL, cost_rub REAL NOT NULL,
    duration_ms INTEGER NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS step_marks (
    vehicle_id TEXT NOT NULL, list_key TEXT NOT NULL, idx INTEGER NOT NULL,
    author TEXT, created_at TEXT NOT NULL,
    PRIMARY KEY (vehicle_id, list_key, idx)
);
CREATE TABLE IF NOT EXISTS reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id INTEGER NOT NULL, vehicle_id TEXT NOT NULL,
    reason TEXT NOT NULL, text TEXT NOT NULL, author TEXT, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reviews (
    message_id INTEGER PRIMARY KEY, reviewed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS llm_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    turn_id INTEGER NOT NULL, step TEXT NOT NULL, model TEXT NOT NULL,
    input_tokens INTEGER NOT NULL, output_tokens INTEGER NOT NULL, cache_read_tokens INTEGER NOT NULL,
    cost_rub REAL NOT NULL, duration_ms INTEGER NOT NULL, created_at TEXT NOT NULL
);
"""


def now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _period(column: str, date_from: str | None, date_to: str | None) -> tuple[list[str], list]:
    """Условие на период по времени ISO. Конец периода включается целиком: дата — весь день, минута — вся минута."""
    where, args = ["1=1"], []
    if date_from:
        where.append(f"{column} >= ?")
        args.append(date_from)
    if date_to:
        where.append(f"substr({column}, 1, {len(date_to)}) <= ?")
        args.append(date_to)
    return where, args


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._db.executescript(SCHEMA)
            # Кто задал вопрос в этом ходе: фильтр выгрузки стоимости по механику. В старых базах колонки нет.
            if "author" not in {r["name"] for r in self._db.execute("PRAGMA table_info(turns)")}:
                self._db.execute("ALTER TABLE turns ADD COLUMN author TEXT")
            self._db.commit()
        journal.init(self)

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def _exec(self, sql: str, args: tuple = ()) -> sqlite3.Cursor:
        with self._lock:
            cur = self._db.execute(sql, args)
            self._db.commit()
            return cur

    def _all(self, sql: str, args: tuple = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._db.execute(sql, args).fetchall()

    # --- чат ---
    def add_message(self, vehicle_id: str, session_id: str | None, role: str, payload: dict) -> dict:
        created = now()
        cur = self._exec(
            "INSERT INTO messages (vehicle_id, session_id, role, payload, created_at) VALUES (?,?,?,?,?)",
            (vehicle_id, session_id, role, json.dumps(payload, ensure_ascii=False), created),
        )
        return {"id": f"m_{cur.lastrowid}", "role": role, "created_at": created, "session_id": session_id, **payload}

    def messages(self, vehicle_id: str) -> list[dict]:
        rows = self._all("SELECT * FROM messages WHERE vehicle_id=? ORDER BY id", (vehicle_id,))
        return [
            {"id": f"m_{r['id']}", "role": r["role"], "created_at": r["created_at"],
             "session_id": r["session_id"], **json.loads(r["payload"])}
            for r in rows
        ]

    def update_message_draft(self, draft: dict) -> None:
        """Обновляет копию черновика внутри сообщения чата, чтобы история показывала актуальный состав."""
        rows = self._all("SELECT id, payload FROM messages WHERE vehicle_id=? AND role='assistant'", (draft["vehicle_id"],))
        for r in rows:
            payload = json.loads(r["payload"])
            if payload.get("draft", {}).get("draft_id") == draft["draft_id"]:
                payload["draft"] = draft
                self._exec("UPDATE messages SET payload=? WHERE id=?", (json.dumps(payload, ensure_ascii=False), r["id"]))

    def clear_messages(self, vehicle_id: str) -> None:
        self._exec("DELETE FROM messages WHERE vehicle_id=?", (vehicle_id,))
        self._exec("DELETE FROM step_marks WHERE vehicle_id=?", (vehicle_id,))

    # --- отметки «сделано» по шагам: видны всем механикам смены ---
    def set_mark(self, vehicle_id: str, list_key: str, idx: int, done: bool, author: str | None) -> None:
        if done:
            self._exec("INSERT OR REPLACE INTO step_marks (vehicle_id, list_key, idx, author, created_at) "
                       "VALUES (?,?,?,?,?)", (vehicle_id, list_key, idx, author, now()))
        else:
            self._exec("DELETE FROM step_marks WHERE vehicle_id=? AND list_key=? AND idx=?", (vehicle_id, list_key, idx))

    def marks(self, vehicle_id: str) -> dict[str, dict[str, dict]]:
        """Отметки по спискам шагов: {«m_12:checks»: {«0»: {author, at}}}."""
        out: dict[str, dict[str, dict]] = {}
        for r in self._all("SELECT * FROM step_marks WHERE vehicle_id=? ORDER BY created_at", (vehicle_id,)):
            out.setdefault(r["list_key"], {})[str(r["idx"])] = {"author": r["author"], "at": r["created_at"]}
        return out

    # --- сообщения механика в поддержку ---
    def add_report(self, message_id: int, vehicle_id: str, reason: str, text: str, author: str | None) -> dict:
        created = now()
        self._exec("INSERT INTO reports (message_id, vehicle_id, reason, text, author, created_at) VALUES (?,?,?,?,?,?)",
                   (message_id, vehicle_id, reason, text, author, created))
        # Новое сообщение возвращает случай в работу, даже если его уже разбирали
        self._exec("DELETE FROM reviews WHERE message_id=?", (message_id,))
        return {"reason": reason, "text": text, "author": author, "created_at": created}

    def _reports(self, vehicle_id: str | None = None) -> dict[int, dict]:
        """Последнее сообщение механика по каждому ответу агента."""
        sql, args = "SELECT * FROM reports ORDER BY id", ()
        if vehicle_id:
            sql, args = "SELECT * FROM reports WHERE vehicle_id=? ORDER BY id", (vehicle_id,)
        return {r["message_id"]: {"reason": r["reason"], "text": r["text"], "author": r["author"],
                                  "created_at": r["created_at"]} for r in self._all(sql, args)}

    def reports_by_message(self, vehicle_id: str) -> dict[str, dict]:
        return {f"m_{k}": v for k, v in self._reports(vehicle_id).items()}

    def message(self, message_id: int) -> dict | None:
        rows = self._all("SELECT * FROM messages WHERE id=?", (message_id,))
        if not rows:
            return None
        r = rows[0]
        return {"id": f"m_{r['id']}", "role": r["role"], "vehicle_id": r["vehicle_id"], "created_at": r["created_at"],
                **json.loads(r["payload"])}

    def audit(self, limit: int = 100) -> list[dict]:
        """Журнал обращений: ответ агента вместе с вопросом, источниками и инструментами."""
        rows = self._all("SELECT * FROM messages WHERE role='assistant' ORDER BY id DESC LIMIT ?", (limit,))
        reviewed = self._reviewed()
        reports = self._reports()
        out = []
        for r in rows:
            payload = json.loads(r["payload"])
            question = self._all(
                "SELECT payload FROM messages WHERE vehicle_id=? AND role='user' AND id<? ORDER BY id DESC LIMIT 1",
                (r["vehicle_id"], r["id"]),
            )
            answer = payload.get("answer") or {}
            draft = payload.get("draft") or {}
            items = [*(answer.get("checks") or []), *(answer.get("repair") or []),
                     *(draft.get("operations") or []), *(draft.get("spare_parts") or [])]
            items += [{"refs": [s["ref"]]} for block in answer.get("conflicts") or [] for s in block["statements"]]
            sources, seen = [], set()
            for item in items:
                for ref in item.get("refs", []):
                    key = (ref["manual_id"], ref["pdf_page"])
                    if key not in seen:
                        seen.add(key)
                        sources.append({"manual_id": ref["manual_id"], "short": ref["short"], "pdf_page": ref["pdf_page"]})
            report = reports.get(r["id"])
            gap = alerts.gap_of(payload, report)
            if gap:
                gap["reviewed_at"] = reviewed.get(r["id"])
            asked = json.loads(question[0]["payload"]) if question else {}
            out.append({
                "id": f"m_{r['id']}", "created_at": r["created_at"], "vehicle_id": r["vehicle_id"],
                "session_id": r["session_id"],
                "question": asked.get("text", ""),
                "author": asked.get("author"),
                "photos": len(asked.get("images") or []),
                "report": report,
                "kind": payload.get("kind"), "answer": payload.get("text", ""),
                "sources": sources,
                "tools": [step["tool"] for step in payload.get("steps", [])],
                "ticket_id": (payload.get("ticket") or {}).get("ticket_id"),
                "usage": payload.get("usage", {}),
                "gap": gap,
            })
        return out

    def _reviewed(self) -> dict[int, str]:
        # Статусы разбора ведёт журнал (app/journal.py), старая таблица reviews перенесена туда
        return journal.reviewed_map(self)

    def set_reviewed(self, message_id: int, reviewed: bool) -> str | None:
        """Администратор разобрал случай без ответа в руководстве (или вернул его в работу)."""
        result = journal.set_status(self, [f"m_{message_id}"], "reviewed" if reviewed else "new")
        return result["at"] if reviewed else None

    def is_assistant_message(self, message_id: int) -> bool:
        return bool(self._all("SELECT 1 FROM messages WHERE id=? AND role='assistant'", (message_id,)))

    def open_gaps(self, limit: int = 500) -> int:
        """Сколько случаев «новый» и «в работе» во всём журнале (повторы считаются одним случаем)."""
        return journal.open_count(self)

    # --- разборы проверок (память по машине, B1) ---
    def save_analysis(self, vehicle_id: str, session_id: str, diagnosis: dict, assessment: dict) -> None:
        self._exec(
            "INSERT OR REPLACE INTO analyses (vehicle_id, session_id, diagnosis, assessment, created_at) VALUES (?,?,?,?,?)",
            (vehicle_id, session_id, json.dumps(diagnosis, ensure_ascii=False),
             json.dumps(assessment, ensure_ascii=False), now()),
        )

    def analysis(self, vehicle_id: str, session_id: str) -> dict | None:
        rows = self._all("SELECT * FROM analyses WHERE vehicle_id=? AND session_id=?", (vehicle_id, session_id))
        if not rows:
            return None
        return {"diagnosis": json.loads(rows[0]["diagnosis"]), "assessment": json.loads(rows[0]["assessment"])}

    # --- черновики заявок ---
    def create_draft(self, vehicle_id: str, session_id: str, payload: dict) -> dict:
        cur = self._exec(
            "INSERT INTO drafts (vehicle_id, session_id, payload, status, created_at) VALUES (?,?,?,?,?)",
            (vehicle_id, session_id, "{}", "draft", now()),
        )
        draft = {**payload, "draft_id": f"d_{cur.lastrowid}", "status": "draft", "ticket_id": None}
        self.save_draft(draft)
        return draft

    def save_draft(self, draft: dict) -> None:
        self._exec(
            "UPDATE drafts SET payload=?, status=? WHERE id=?",
            (json.dumps(draft, ensure_ascii=False), draft["status"], int(draft["draft_id"].split("_")[1])),
        )
        self.update_message_draft(draft)

    def draft(self, draft_id: str) -> dict | None:
        try:
            key = int(draft_id.split("_")[1])
        except (IndexError, ValueError):
            return None
        rows = self._all("SELECT payload FROM drafts WHERE id=?", (key,))
        return json.loads(rows[0]["payload"]) if rows else None

    # --- заявки ---
    def add_ticket(self, ticket: dict) -> dict:
        created = now()
        full = {**ticket, "created_at": created}
        self._exec(
            "INSERT INTO tickets (ticket_id, vehicle_id, session_id, payload, created_at) VALUES (?,?,?,?,?)",
            (ticket["ticket_id"], ticket["vehicle_id"], ticket["session_id"],
             json.dumps(full, ensure_ascii=False), created),
        )
        return full

    def tickets(self, vehicle_id: str | None = None) -> list[dict]:
        if vehicle_id:
            rows = self._all("SELECT payload FROM tickets WHERE vehicle_id=? ORDER BY id", (vehicle_id,))
        else:
            rows = self._all("SELECT payload FROM tickets ORDER BY id")
        return [json.loads(r["payload"]) for r in rows]

    def tickets_by_vehicle(self) -> dict[str, list[dict]]:
        out: dict[str, list[dict]] = {}
        for t in self.tickets():
            out.setdefault(t["vehicle_id"], []).append(t)
        return out

    # --- журнал модели и стоимость ---
    def start_turn(self, vehicle_id: str, session_id: str | None, author: str | None = None) -> int:
        return self._exec(
            "INSERT INTO turns (vehicle_id, session_id, author, created_at) VALUES (?,?,?,?)",
            (vehicle_id, session_id, author, now()),
        ).lastrowid

    def finish_turn(self, turn_id: int, kind: str, duration_ms: int, starts_scenario: bool) -> None:
        row = self._all("SELECT vehicle_id, session_id FROM turns WHERE id=?", (turn_id,))[0]
        scenario_id = turn_id
        if not starts_scenario:
            prev = self._all(
                "SELECT scenario_id FROM turns WHERE vehicle_id=? AND session_id IS ? AND id<? AND scenario_id IS NOT NULL "
                "ORDER BY id DESC LIMIT 1",
                (row["vehicle_id"], row["session_id"], turn_id),
            )
            if prev:
                scenario_id = prev[0]["scenario_id"]
        self._exec("UPDATE turns SET kind=?, duration_ms=?, scenario_id=? WHERE id=?",
                   (kind, duration_ms, scenario_id, turn_id))

    def log_llm_call(self, turn_id: int, step: str, model: str, input_tokens: int, output_tokens: int,
                     cache_read_tokens: int, cost_rub: float, duration_ms: int) -> None:
        self._exec(
            "INSERT INTO llm_calls (turn_id, step, model, input_tokens, output_tokens, cache_read_tokens, cost_rub, "
            "duration_ms, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (turn_id, step, model, input_tokens, output_tokens, cache_read_tokens, cost_rub, duration_ms, now()),
        )

    def log_stt(self, model: str, seconds: float, cost_rub: float, duration_ms: int) -> None:
        self._exec("INSERT INTO stt_calls (model, seconds, cost_rub, duration_ms, created_at) VALUES (?,?,?,?,?)",
                   (model, seconds, cost_rub, duration_ms, now()))

    def llm_calls(self, date_from: str | None = None, date_to: str | None = None, model: str | None = None,
                  vehicle_id: str | None = None, mechanic: str | None = None) -> list[dict]:
        """Вызовы модели вместе с ходом агента, для выгрузки расчёта стоимости. Период считается по времени хода."""
        where, args = _period("t.created_at", date_from, date_to)
        for column, value in (("c.model", model), ("t.vehicle_id", vehicle_id), ("t.author", mechanic)):
            if value:
                where.append(f"{column} = ?")
                args.append(value)
        rows = self._all(
            "SELECT c.id, c.created_at, c.step, c.model, c.input_tokens, c.output_tokens, c.cache_read_tokens, "
            "c.cost_rub, c.duration_ms, t.id AS turn_id, t.scenario_id, t.vehicle_id, t.session_id, t.author, t.kind "
            "FROM llm_calls c JOIN turns t ON t.id = c.turn_id WHERE " + " AND ".join(where) + " ORDER BY c.id",
            tuple(args),
        )
        return [dict(r) for r in rows]

    def stt_calls(self, date_from: str | None = None, date_to: str | None = None) -> list[dict]:
        where, args = _period("created_at", date_from, date_to)
        return [dict(r) for r in self._all("SELECT * FROM stt_calls WHERE " + " AND ".join(where) + " ORDER BY id",
                                           tuple(args))]

    def usage_summary(self, since: str | None = None) -> dict:
        """Сводка расхода модели. since: считать только ходы не раньше этого времени (ISO), чтобы
        в расчёт стоимости не попали отладочные прогоны на других моделях."""
        # Время в базе записано в часовом поясе процесса (в контейнере UTC), since может прийти с другим поясом:
        # сравниваем через datetime() SQLite, она приводит обе стороны к UTC
        since = since or "0001-01-01T00:00:00+00:00"
        per_step = self._all(
            "SELECT c.step, c.model, COUNT(*) AS calls, SUM(c.input_tokens) AS inp, SUM(c.output_tokens) AS outp, "
            "SUM(c.cache_read_tokens) AS cache, SUM(c.cost_rub) AS cost, COUNT(DISTINCT t.scenario_id) AS scenarios "
            "FROM llm_calls c JOIN turns t ON t.id=c.turn_id WHERE datetime(t.created_at) >= datetime(?) "
            "GROUP BY c.step, c.model ORDER BY c.step", (since,)
        )
        scenarios = self._all(
            "SELECT t.scenario_id, COUNT(DISTINCT t.id) AS turns, COUNT(c.id) AS calls, "
            "COALESCE(SUM(c.input_tokens),0) AS inp, COALESCE(SUM(c.output_tokens),0) AS outp, "
            "COALESCE(SUM(c.cost_rub),0) AS cost, COALESCE(SUM(c.duration_ms),0) AS ms "
            "FROM turns t LEFT JOIN llm_calls c ON c.turn_id=t.id "
            "WHERE t.scenario_id IS NOT NULL AND datetime(t.created_at) >= datetime(?) GROUP BY t.scenario_id", (since,)
        )
        n = len(scenarios) or 1
        speech = self._all(
            "SELECT model, COUNT(*) AS calls, SUM(seconds) AS sec, SUM(cost_rub) AS cost, SUM(duration_ms) AS ms "
            "FROM stt_calls WHERE datetime(created_at) >= datetime(?) GROUP BY model", (since,)
        )
        return {
            "speech": [
                {"model": r["model"], "calls": r["calls"], "seconds_per_call": round(r["sec"] / r["calls"], 1),
                 "cost_rub_per_call": round(r["cost"] / r["calls"], 4), "duration_ms_per_call": round(r["ms"] / r["calls"])}
                for r in speech
            ],
            "scenarios": len(scenarios),
            "per_scenario_avg": {
                "turns": round(sum(s["turns"] for s in scenarios) / n, 2),
                "llm_calls": round(sum(s["calls"] for s in scenarios) / n, 2),
                "input_tokens": round(sum(s["inp"] for s in scenarios) / n),
                "output_tokens": round(sum(s["outp"] for s in scenarios) / n),
                "cost_rub": round(sum(s["cost"] for s in scenarios) / n, 4),
                "duration_ms": round(sum(s["ms"] for s in scenarios) / n),
            },
            "per_step": [
                {
                    "step": r["step"], "model": r["model"],
                    "calls_per_scenario": round(r["calls"] / n, 2),
                    "input_tokens_per_call": round(r["inp"] / r["calls"]),
                    "output_tokens_per_call": round(r["outp"] / r["calls"]),
                    "cache_read_tokens_per_call": round(r["cache"] / r["calls"]),
                    "cost_rub_per_scenario": round(r["cost"] / n, 4),
                }
                for r in per_step
            ],
        }
