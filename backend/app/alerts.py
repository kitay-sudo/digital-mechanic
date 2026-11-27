"""Случаи для администратора: в руководстве нет ответа (Q&A с заказчиком 27.11).

Механик в таком случае получает честный отказ и конкретное действие. Администратор должен узнать
об этом сразу: поправить базу знаний, задать вопрос производителю, не оставить механика с вопросом.
Такие ответы помечаются в журнале до тех пор, пока администратор не отметит их разобранными.
Если задан ALERT_WEBHOOK_URL, сервер отправляет туда сообщение JSON с полем text.

Когда отправлять (ALERT_MODE): digest (по умолчанию) — сразу только срочное, остальное одной сводкой
за день (app/digest.py); instant — каждый случай сразу.
"""
from __future__ import annotations

import asyncio
import logging
import os

import httpx

log = logging.getLogger("mechanic")

# Короткая подпись для строки журнала и полная — для уведомления администратору
LABELS = {
    "report": "От механика",
    "no_answer": "Нет в руководстве",
    "kb_missing": "Нет руководств",
    "ml_mismatch": "Ошибка диагностики",
    "injection": "Посторонний текст",
}
TITLES = {
    "report": "Механик сообщил о проблеме",
    "no_answer": "Нет ответа в руководстве",
    "kb_missing": "Руководства не загружены в базу знаний",
    "ml_mismatch": "Ошибка модели диагностики: тип неисправности не подходит двигателю",
    "injection": "Посторонний текст в данных диагностики",
}
# Срочное уходит сразу и в режиме сводки: без руководств и с ошибкой диагностики механик стоит
URGENT = {"kb_missing", "ml_mismatch"}
_KB_EMPTY_MARK = "не загружены в базу знаний"
_tasks: set[asyncio.Task] = set()


def gap_of(payload: dict, report: dict | None = None) -> dict | None:
    """Что в ответе агента требует внимания администратора. None — ответ обычный.

    report — сообщение механика об этом ответе («Сообщить о проблеме»): оно важнее остального.
    """
    if report:
        return {"type": "report", "label": LABELS["report"], "title": f"{TITLES['report']}: {report['reason']}"}
    kind = payload.get("kind")
    answer = payload.get("answer") or {}
    flags = (payload.get("assessment") or {}).get("flags") or {}
    if kind in ("ticket_created", "ticket_draft"):
        return None
    if kind == "verdict" and flags.get("engine_mismatch"):
        kind_of_gap = "ml_mismatch"
    elif _KB_EMPTY_MARK in (payload.get("text") or ""):
        kind_of_gap = "kb_missing"
    elif answer.get("not_found") or answer.get("recommendation_text"):
        kind_of_gap = "no_answer"
    elif kind == "verdict" and (payload.get("diagnosis") or {}).get("description_flagged"):
        # В описании от ML-сервиса были указания для агента: они отброшены, но администратор должен знать
        kind_of_gap = "injection"
    else:
        return None
    return {"type": kind_of_gap, "label": LABELS[kind_of_gap], "title": TITLES[kind_of_gap]}


def message_text(gap: dict, vehicle: dict, question: str, answer_text: str) -> str:
    return (f"{gap['title']}. Машина {vehicle.get('model') or vehicle['vehicle_id']}, госномер {vehicle['vehicle_id']}, "
            f"двигатель {vehicle.get('engine_model', '—')}.\nВопрос механика: {question or '—'}\n"
            f"Ответ агента: {answer_text or '—'}")


async def _post(url: str, body: dict) -> None:
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(url, json=body)
            response.raise_for_status()
    except Exception as exc:  # сбой уведомления не должен мешать механику
        log.warning("Уведомление администратору не отправлено: %s", exc)


def alert_mode() -> str:
    """instant — каждый случай сразу, digest — сразу только срочное, остальное в сводке за день."""
    return "instant" if os.environ.get("ALERT_MODE", "digest").strip().lower() == "instant" else "digest"


def sends_now(gap_type: str) -> bool:
    return alert_mode() == "instant" or gap_type in URGENT


def send(url: str, body: dict) -> None:
    """Отправляет сообщение в фоне, ответ механику его не ждёт."""
    if not url:
        return
    task = asyncio.create_task(_post(url, body))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


def notify(url: str, gap: dict, vehicle: dict, question: str, answer_text: str, created_at: str) -> None:
    """Уведомление о случае. В режиме сводки несрочное не отправляется: оно попадёт в сводку за день."""
    if not url or not sends_now(gap["type"]):
        return
    send(url, {
        "text": message_text(gap, vehicle, question, answer_text),
        "type": gap["type"], "vehicle_id": vehicle["vehicle_id"], "engine_model": vehicle.get("engine_model"),
        "question": question, "answer": answer_text, "created_at": created_at,
    })
