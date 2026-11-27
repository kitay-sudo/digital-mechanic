"""Сводка смены для главного механика и метрики пилота за период.

Смена — период с/по (по умолчанию сегодня по местному времени): кто работал (авторы вопросов,
отметок шагов и сообщений администратору), сколько было вопросов, какие шаги отмечены сделанными
и кем, какие заявки созданы, сколько случаев ждёт разбора.

Метрики пилота: время от вердикта до заявки (первое сообщение-вердикт по проверке → создание заявки),
доля честных отказов (ответы «в руководстве нет» среди ответов), сколько вердиктов с предупреждением
«Повтор после ремонта», среднее время ответа и стоимость.
"""
from __future__ import annotations

import json
from datetime import datetime
from statistics import median

from . import fleet, journal

# Время записи хранится строкой ISO со смещением: сравнение через julianday учитывает часовой пояс
_IN = " AND julianday({col}) >= julianday(?) AND julianday({col}) < julianday(?)"
REPEAT_MARK = "Повтор после ремонта"


def _in(col: str = "created_at") -> str:
    return _IN.format(col=col)


def _title(vehicle_id: str) -> str:
    vehicle = fleet.get_vehicle(vehicle_id)
    return fleet.title_of(vehicle) if vehicle else vehicle_id


def summary(store, lo: datetime, hi: datetime) -> dict:
    args = (lo.isoformat(), hi.isoformat())
    journal.sync(store)
    users = store._all("SELECT vehicle_id, payload, created_at FROM messages WHERE role='user'" + _in(), args)
    answers = store._all("SELECT COUNT(*) AS n FROM messages WHERE role='assistant'" + _in(), args)[0]["n"]
    marks = store._all("SELECT * FROM step_marks WHERE 1=1" + _in() + " ORDER BY created_at DESC", args)
    messages = store._all("SELECT author, created_at FROM reports WHERE 1=1" + _in(), args)
    messages += store._all("SELECT author, created_at FROM admin_messages WHERE 1=1" + _in(), args)
    tickets = store._all("SELECT payload FROM tickets WHERE 1=1" + _in() + " ORDER BY id DESC", args)

    people: dict[str | None, dict] = {}

    def seen(name: str | None, at: str, field: str) -> None:
        name = (name or "").strip() or None
        row = people.setdefault(name, {"name": name, "questions": 0, "marks": 0, "messages": 0,
                                       "first_at": at, "last_at": at})
        row[field] += 1
        if journal.ts_of(at) < journal.ts_of(row["first_at"]):
            row["first_at"] = at
        if journal.ts_of(at) > journal.ts_of(row["last_at"]):
            row["last_at"] = at

    for u in users:
        seen(json.loads(u["payload"]).get("author"), u["created_at"], "questions")
    for m in marks:
        seen(m["author"], m["created_at"], "marks")
    for m in messages:
        seen(m["author"], m["created_at"], "messages")

    # Текст отмеченного шага — из ответа агента, к которому относится список шагов
    ids = sorted({int(m["list_key"].split(":")[0][2:]) for m in marks})
    payloads = {r["id"]: json.loads(r["payload"]) for r in store._all(
        f"SELECT id, payload FROM messages WHERE id IN ({','.join('?' * len(ids)) or 'NULL'})", tuple(ids))}
    steps = []
    for m in marks:
        key, kind = m["list_key"].split(":")
        items = ((payloads.get(int(key[2:])) or {}).get("answer") or {}).get(kind) or []
        text = items[m["idx"]].get("text", "") if m["idx"] < len(items) else ""
        steps.append({"vehicle_id": m["vehicle_id"], "vehicle_title": _title(m["vehicle_id"]), "list": kind,
                      "index": m["idx"], "step": text or f"Шаг {m['idx'] + 1}", "author": m["author"],
                      "at": m["created_at"]})

    created = []
    for row in tickets:
        t = json.loads(row["payload"])
        created.append({"ticket_id": t["ticket_id"], "vehicle_id": t["vehicle_id"], "vehicle_title": _title(t["vehicle_id"]),
                        "session_id": t.get("session_id"), "created_at": t.get("created_at"),
                        "urgency": t.get("urgency"), "anomaly_type": t.get("anomaly_type"),
                        "conclusion": t.get("conclusion") or ""})

    period = {"from_ts": lo.timestamp(), "to_ts": hi.timestamp()}
    mechanics = sorted(people.values(), key=lambda p: (p["name"] is None, -(p["questions"] + p["marks"] + p["messages"]),
                                                       p["name"] or ""))
    return {
        "from": lo.isoformat(), "to": hi.isoformat(),
        "totals": {"questions": len(users), "answers": answers, "vehicles": len({u["vehicle_id"] for u in users}),
                   "marks": len(steps), "tickets": len(created), "open_cases": journal.open_count(store, period),
                   "open_total": journal.open_count(store)},
        "mechanics": mechanics, "marks": steps, "tickets": created,
    }


def metrics(store, lo: datetime, hi: datetime) -> dict:
    args = (lo.isoformat(), hi.isoformat())
    payloads = [json.loads(r["payload"]) for r in store._all(
        "SELECT payload FROM messages WHERE role='assistant'" + _in(), args)]
    answers = [p for p in payloads if p.get("kind") == "answer"]
    refusals = sum(bool((p.get("answer") or {}).get("not_found")) for p in answers)
    verdicts = [p for p in payloads if p.get("kind") == "verdict"]
    repeats = sum(any(REPEAT_MARK in str(w) for w in (p.get("assessment") or {}).get("warnings") or [])
                  for p in verdicts)
    durations = [p["usage"]["duration_ms"] for p in payloads
                 if isinstance((p.get("usage") or {}).get("duration_ms"), (int, float))]
    # От первого вердикта по проверке до создания заявки по ней
    pairs = store._all(
        "SELECT t.created_at AS ticket_at, (SELECT m.created_at FROM messages m WHERE m.role='assistant' "
        "AND m.vehicle_id=t.vehicle_id AND m.session_id=t.session_id AND json_extract(m.payload, '$.kind')='verdict' "
        "ORDER BY m.id LIMIT 1) AS verdict_at FROM tickets t WHERE 1=1" + _in("t.created_at"), args)
    minutes = [(journal.ts_of(p["ticket_at"]) - journal.ts_of(p["verdict_at"])) / 60 for p in pairs
               if p["verdict_at"] and journal.ts_of(p["ticket_at"]) >= journal.ts_of(p["verdict_at"])]
    cost = store._all("SELECT COALESCE(SUM(cost_rub), 0) AS s FROM llm_calls WHERE 1=1" + _in(), args)[0]["s"]
    speech = store._all("SELECT COALESCE(SUM(cost_rub), 0) AS s FROM stt_calls WHERE 1=1" + _in(), args)[0]["s"]
    return {
        "from": lo.isoformat(), "to": hi.isoformat(),
        "verdicts": len(verdicts),
        "verdict_to_ticket": {"count": len(minutes), "avg_min": round(sum(minutes) / len(minutes), 1) if minutes else None,
                              "median_min": round(median(minutes), 1) if minutes else None},
        "refusals": {"answers": len(answers), "not_found": refusals,
                     "share": round(refusals / len(answers), 3) if answers else None},
        "repeat_after_repair": repeats,
        "response": {"count": len(durations), "avg_ms": round(sum(durations) / len(durations)) if durations else None},
        "cost": {"total_rub": round(cost, 2), "per_answer_rub": round(cost / len(payloads), 2) if payloads else None,
                 "speech_rub": round(speech, 2)},
    }
