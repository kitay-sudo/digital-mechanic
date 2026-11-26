"""Парк машин и история проверок из vehicles.json (материалы заказчика)."""
from __future__ import annotations

import json
from functools import lru_cache

from . import rules
from .config import get_settings
from .kb.text import sanitize_description
from .manuals import manuals_for_engine

SESSION_FIELDS = (
    "session_id", "checked_at", "status", "anomaly_type", "anomaly_title",
    "anomaly_score", "confidence", "signal_quality", "description",
)
STATUS_ORDER = {"quarantine": 0, "attention": 1, "ok": 2}
PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2, None: 3}


@lru_cache
def _load() -> dict[str, dict]:
    data = json.loads(get_settings().fleet_path.read_text(encoding="utf-8"))
    return {v["vehicle_id"]: v for v in data["vehicles"]}


@lru_cache
def fault_types() -> dict[str, str]:
    data = json.loads(get_settings().fault_types_path.read_text(encoding="utf-8"))
    return {f["code"]: f["title"] for f in data}


def get_vehicle(vehicle_id: str) -> dict | None:
    return _load().get(vehicle_id)


def get_session(vehicle: dict, session_id: str) -> dict | None:
    return next((s for s in vehicle["sessions"] if s["session_id"] == session_id), None)


def previous_sessions(vehicle: dict, session_id: str) -> list[dict]:
    out = []
    for s in vehicle["sessions"]:
        if s["session_id"] == session_id:
            break
        out.append(s)
    return out


def title_of(vehicle: dict) -> str:
    return vehicle.get("model") or vehicle.get("make") or vehicle["vehicle_id"]


def brief(vehicle: dict, tickets: list[dict]) -> dict:
    conf_min = get_settings().confidence_min
    last = vehicle["sessions"][-1] if vehicle["sessions"] else None
    out = {
        "vehicle_id": vehicle["vehicle_id"],
        "garage_no": vehicle.get("garage_no"),
        "make": vehicle.get("make"),
        "model": vehicle.get("model"),
        "title": title_of(vehicle),
        "vehicle_type": vehicle.get("vehicle_type"),
        "engine_model": vehicle.get("engine_model"),
        "fuel": vehicle.get("fuel"),
        "last_session": {k: last.get(k) for k in SESSION_FIELDS if k != "description"} if last else None,
        "sessions_count": len(vehicle["sessions"]),
        "tickets": [
            {"ticket_id": t["ticket_id"], "session_id": t["session_id"], "created_at": t["created_at"]}
            for t in tickets
        ],
    }
    out.update(rules.fleet_status(vehicle, conf_min))
    return out


def fleet(tickets_by_vehicle: dict[str, list[dict]]) -> dict:
    vehicles = [brief(v, tickets_by_vehicle.get(v["vehicle_id"], [])) for v in _load().values()]
    vehicles.sort(key=lambda b: (
        STATUS_ORDER[b["fleet_status"]],
        PRIORITY_ORDER[b["priority"]],
        -(b["last_session"]["anomaly_score"] or 0) if b["last_session"] else 0,
        b["vehicle_id"],
    ))
    summary = {
        "total": len(vehicles),
        "ok": sum(b["fleet_status"] == "ok" for b in vehicles),
        "attention": sum(b["fleet_status"] == "attention" for b in vehicles),
        "quarantine": sum(b["fleet_status"] == "quarantine" for b in vehicles),
        "recheck": sum(b["needs_recheck"] for b in vehicles),
    }
    return {"summary": summary, "vehicles": vehicles}


def detail(vehicle: dict, tickets: list[dict]) -> dict:
    out = brief(vehicle, tickets)
    ticket_by_session = {t["session_id"]: t["ticket_id"] for t in tickets}
    out["sessions"] = [
        {**{k: s.get(k) for k in SESSION_FIELDS},
         "description": sanitize_description(s.get("description") or "")[0],
         "ticket_id": ticket_by_session.get(s["session_id"])}
        for s in vehicle["sessions"]
    ]
    out["manuals"] = [m.public() for m in manuals_for_engine(vehicle["engine_model"])]
    out["trend"] = rules.trend(vehicle["sessions"])
    out["tickets"] = tickets
    return out
