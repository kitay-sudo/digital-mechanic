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
CREATE TABLE IF NOT EXISTS llm_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    turn_id INTEGER NOT NULL, step TEXT NOT NULL, model TEXT NOT NULL,
    input_tokens INTEGER NOT NULL, output_tokens INTEGER NOT NULL, cache_read_tokens INTEGER NOT NULL,
    cost_rub REAL NOT NULL, duration_ms INTEGER NOT NULL, created_at TEXT NOT NULL
);
"""


def now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._db.executescript(SCHEMA)
            self._db.commit()

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

    def audit(self, limit: int = 100) -> list[dict]:
        """Журнал обращений: ответ агента вместе с вопросом, источниками и инструментами."""
        rows = self._all("SELECT * FROM messages WHERE role='assistant' ORDER BY id DESC LIMIT ?", (limit,))
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
            sources, seen = [], set()
            for item in items:
                for ref in item.get("refs", []):
                    key = (ref["manual_id"], ref["pdf_page"])
                    if key not in seen:
                        seen.add(key)
                        sources.append({"manual_id": ref["manual_id"], "short": ref["short"], "pdf_page": ref["pdf_page"]})
            out.append({
                "id": f"m_{r['id']}", "created_at": r["created_at"], "vehicle_id": r["vehicle_id"],
                "session_id": r["session_id"],
                "question": json.loads(question[0]["payload"]).get("text", "") if question else "",
                "kind": payload.get("kind"), "answer": payload.get("text", ""),
                "sources": sources,
                "tools": [step["tool"] for step in payload.get("steps", [])],
                "ticket_id": (payload.get("ticket") or {}).get("ticket_id"),
                "usage": payload.get("usage", {}),
            })
        return out

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
    def start_turn(self, vehicle_id: str, session_id: str | None) -> int:
        return self._exec(
            "INSERT INTO turns (vehicle_id, session_id, created_at) VALUES (?,?,?)", (vehicle_id, session_id, now())
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

    def usage_summary(self) -> dict:
        per_step = self._all(
            "SELECT c.step, c.model, COUNT(*) AS calls, SUM(c.input_tokens) AS inp, SUM(c.output_tokens) AS outp, "
            "SUM(c.cache_read_tokens) AS cache, SUM(c.cost_rub) AS cost, COUNT(DISTINCT t.scenario_id) AS scenarios "
            "FROM llm_calls c JOIN turns t ON t.id=c.turn_id GROUP BY c.step, c.model ORDER BY c.step"
        )
        scenarios = self._all(
            "SELECT t.scenario_id, COUNT(DISTINCT t.id) AS turns, COUNT(c.id) AS calls, "
            "COALESCE(SUM(c.input_tokens),0) AS inp, COALESCE(SUM(c.output_tokens),0) AS outp, "
            "COALESCE(SUM(c.cost_rub),0) AS cost, COALESCE(SUM(c.duration_ms),0) AS ms "
            "FROM turns t LEFT JOIN llm_calls c ON c.turn_id=t.id WHERE t.scenario_id IS NOT NULL GROUP BY t.scenario_id"
        )
        n = len(scenarios) or 1
        return {
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
