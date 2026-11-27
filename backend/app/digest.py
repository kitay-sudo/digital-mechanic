"""Сводка администратору раз в день и срочные уведомления о сбоях.

ALERT_MODE=digest (по умолчанию): сразу уходит только срочное — руководства не загружены (kb_missing),
ошибка модели диагностики (ml_mismatch) и сбои агента (ход закончился ошибкой, механик остался без
ответа). Остальное — вопросы без ответа в руководстве, сообщения механиков, посторонний текст
в данных диагностики — собирается в одно сообщение за день и уходит в DIGEST_TIME (по умолчанию 18:00)
по местному времени APP_TZ на ALERT_WEBHOOK_URL. ALERT_MODE=instant: всё сразу, сводки нет.

Фоновая задача запускается в lifespan сервера и раз в полминуты смотрит, не пора ли.
Отправленная сводка записывается в базу: после перезапуска сервера она не повторяется.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
from datetime import date, datetime, time, timedelta

from . import alerts, fleet, journal

log = logging.getLogger("mechanic")
TICK_S = 30
MAX_LINES = 15


def digest_time() -> time:
    value = os.environ.get("DIGEST_TIME", "18:00").strip()
    match = re.fullmatch(r"(\d{1,2}):(\d{2})", value)
    if match and int(match.group(1)) < 24 and int(match.group(2)) < 60:
        return time(int(match.group(1)), int(match.group(2)))
    log.warning("DIGEST_TIME=%s не похоже на ЧЧ:ММ, сводка уйдёт в 18:00", value)
    return time(18, 0)


def _day_bounds(day: date) -> tuple[datetime, datetime]:
    start = datetime.combine(day, time(0), journal.local_tz())
    return start, start + timedelta(days=1)


def _count(store, sql: str, start: datetime, end: datetime) -> int:
    return store._all(sql + " AND julianday(created_at) >= julianday(?) AND julianday(created_at) < julianday(?)",
                      (start.isoformat(), end.isoformat()))[0]["n"]


def _case_line(item: dict) -> str:
    label = item["gap"]["label"] if item.get("gap") else "Обращение"
    if item["repeats"] > 1:
        label += f", повторилось {item['repeats']} раз"
    text = item["question"] or item["answer"]
    if item.get("report"):
        report = item["report"]
        text = report["reason"] + (f": {report['text']}" if report["text"] else "")
    text = text if len(text) <= 120 else text[:117].rstrip() + "…"
    who = (item.get("report") or {}).get("author") or item.get("author")
    where = [item["vehicle_id"] or "без машины"]
    if item.get("engine_model"):
        where.append(item["engine_model"])
    if who:
        where.append(f"механик {who}")
    return f"— {label}: «{text}» ({', '.join(where)})"


def build(store, day: date | None = None) -> dict:
    """Текст сводки за день: сколько было обращений и какие случаи ждут разбора."""
    day = day or datetime.now(journal.local_tz()).date()
    start, end = _day_bounds(day)
    journal.sync(store)
    questions = _count(store, "SELECT COUNT(*) AS n FROM messages WHERE role='user'", start, end)
    answers = _count(store, "SELECT COUNT(*) AS n FROM messages WHERE role='assistant'", start, end)
    tickets = _count(store, "SELECT COUNT(*) AS n FROM tickets WHERE 1=1", start, end)
    failures = store._all(
        "SELECT COUNT(*) AS n FROM turns WHERE kind='error' AND julianday(created_at) >= julianday(?) "
        "AND julianday(created_at) < julianday(?)", (start.isoformat(), end.isoformat()))[0]["n"]
    period = {"from_ts": start.timestamp(), "to_ts": end.timestamp()}
    cases = journal.page(store, period, "open", 1, MAX_LINES)
    open_total = journal.open_count(store)
    lines = [f"Сводка за {day.strftime('%d.%m.%Y')}",
             f"Вопросов механиков: {questions}. Ответов агента: {answers}. Заявок создано: {tickets}."]
    if failures:
        lines.append(f"Сбоев агента: {failures}.")
    if cases["total"]:
        lines.append(f"Ждут разбора случаи за день: {cases['total']}.")
        lines += [_case_line(item) for item in cases["items"]]
        if cases["total"] > len(cases["items"]):
            lines.append(f"И ещё {cases['total'] - len(cases['items'])} в журнале.")
    else:
        lines.append("Новых случаев за день нет.")
    if open_total > cases["total"]:
        lines.append(f"Всего в журнале ждут разбора: {open_total}.")
    return {"day": day.isoformat(), "text": "\n".join(lines), "questions": questions, "answers": answers,
            "tickets": tickets, "failures": failures, "cases": cases["total"], "open_total": open_total,
            "empty": not (questions or answers or cases["total"] or failures)}


def sent_at(store, day: date) -> str | None:
    return journal.meta(store, f"digest:{day.isoformat()}")


def _failure_alert(store) -> str | None:
    """Сбои агента с прошлой проверки: ход закончился ошибкой. Уходит сразу в любом режиме."""
    seen = journal.meta(store, "failures_seen")
    last = store._all("SELECT COALESCE(MAX(id), 0) AS n FROM turns")[0]["n"]
    if seen is None:  # первый запуск: о старых сбоях не пишем
        journal.set_meta(store, "failures_seen", str(last))
        return None
    rows = store._all("SELECT vehicle_id FROM turns WHERE kind='error' AND id>? AND id<=? ORDER BY id",
                      (int(seen), last))
    journal.set_meta(store, "failures_seen", str(last))
    if not rows:
        return None
    vehicles = sorted({r["vehicle_id"] for r in rows})
    titled = []
    for vehicle_id in vehicles[:10]:
        vehicle = fleet.get_vehicle(vehicle_id)
        titled.append(f"{vehicle_id} ({fleet.title_of(vehicle)})" if vehicle else vehicle_id)
    return (f"Сбой агента: {len(rows)} {'ответ не получен' if len(rows) == 1 else 'ответов не получено'}. "
            f"Машины: {', '.join(titled)}. Механикам нужно повторить запрос, проверьте доступность модели.")


async def tick(store, url: str, moment: datetime | None = None) -> list[str]:
    """Одна проверка: срочное о сбоях сразу, сводка за день — когда наступило DIGEST_TIME. Отдаёт отправленное."""
    if not url:
        return []
    moment = (moment or datetime.now(journal.local_tz())).astimezone(journal.local_tz())
    sent: list[str] = []
    failure = _failure_alert(store)
    if failure:
        await alerts._post(url, {"text": failure, "type": "failure"})
        sent.append(failure)
    day = moment.date()
    if alerts.alert_mode() == "digest" and moment.time() >= digest_time() and not sent_at(store, day):
        summary = build(store, day)
        journal.set_meta(store, f"digest:{day.isoformat()}", journal.now())
        if not summary["empty"]:  # пустой день — без сообщения
            await alerts._post(url, {"text": summary["text"], "type": "digest", "day": summary["day"]})
            sent.append(summary["text"])
    return sent


async def run(get_store, get_url) -> None:
    """Фоновая задача сервера: проверка раз в TICK_S секунд."""
    while True:
        try:
            await tick(get_store(), get_url())
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # сбой сводки не должен ронять сервер
            log.warning("Сводка администратору не отправлена: %s", exc)
        await asyncio.sleep(TICK_S)
