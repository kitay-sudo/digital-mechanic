"""Журнал активности стенда и уведомления в Telegram: входы механиков и администратора, вопросы агенту.

Каждое событие пишется строкой JSON в DATA_DIR/activity.log: время по Москве, событие, кто, машина, текст
вопроса, IP и браузер. PIN и пароли не пишутся. Если заданы TELEGRAM_BOT_TOKEN и TELEGRAM_CHAT_ID, короткое
сообщение уходит в Telegram. Отправка идёт в фоне и никогда не ломает ответ пользователю.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from datetime import datetime

import httpx

from .config import get_settings
from .journal import local_tz

log = logging.getLogger("mechanic")

TITLES = {
    "mechanic_login": "Вход механика",
    "mechanic_login_failed": "Неверный PIN механика",
    "admin_login": "Вход администратора",
    "admin_login_failed": "Неверный вход администратора",
    "question": "Вопрос в чате",
    "api_question": "Вопрос через API",
    "api_diagnose": "Разбор проверки через API",
}
# Пауза, после которой новое событие помечается как начало проверки стенда
QUIET_SECONDS = 30 * 60
_last_event = 0.0
_tasks: set[asyncio.Task] = set()


def _now() -> datetime:
    return datetime.now(local_tz())


def client(headers) -> dict:
    """IP и браузер посетителя. nginx дописывает адрес посетителя в конец X-Forwarded-For: последний адрес
    поставил свой прокси, начало списка мог подделать сам посетитель."""
    forwarded = (headers.get("x-forwarded-for") or "").split(",")[-1].strip()
    return {"ip": forwarded or headers.get("x-real-ip") or "", "agent": (headers.get("user-agent") or "")[:160]}


def _browser(agent: str) -> str:
    a = agent.lower()
    device = "телефон" if ("mobile" in a or "android" in a or "iphone" in a) else "компьютер"
    for mark, name in (("edg/", "Edge"), ("yabrowser", "Яндекс Браузер"), ("opr/", "Opera"), ("firefox", "Firefox"),
                       ("chrome", "Chrome"), ("safari", "Safari"), ("python", "скрипт"), ("curl", "curl")):
        if mark in a:
            return f"{name}, {device}"
    return device if agent else ""


def message(event: str, fields: dict, after_pause: bool) -> str:
    lines = []
    if after_pause:
        lines.append("Стенд начали проверять: первое действие после паузы")
    lines.append(TITLES.get(event, event))
    for key, label in (("who", "Кто"), ("vehicle", "Машина"), ("text", "Текст")):
        if fields.get(key):
            lines.append(f"{label}: {str(fields[key])[:300]}")
    where = ", ".join(x for x in (fields.get("ip"), _browser(fields.get("agent", ""))) if x)
    if where:
        lines.append(f"Откуда: {where}")
    return "\n".join(lines)


def _write(record: dict) -> None:
    path = get_settings().data_dir / "activity.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


async def send_telegram(text: str) -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat:
        return
    try:
        async with httpx.AsyncClient(timeout=8) as http:
            r = await http.post(f"https://api.telegram.org/bot{token}/sendMessage",
                                json={"chat_id": chat, "text": text, "disable_web_page_preview": True})
            if r.status_code >= 400:
                log.warning("Telegram не принял уведомление: %s", r.status_code)
    except httpx.HTTPError as exc:
        log.warning("Уведомление в Telegram не отправлено: %s", exc.__class__.__name__)


def record(event: str, headers=None, **fields) -> None:
    """Записать событие и отправить уведомление. Не бросает исключений."""
    global _last_event
    try:
        moment = time.time()
        after_pause = moment - _last_event > QUIET_SECONDS
        _last_event = moment
        data = {"time": _now().isoformat(timespec="seconds"), "event": event,
                **{k: v for k, v in fields.items() if v not in (None, "")}}
        if headers is not None:
            data.update({k: v for k, v in client(headers).items() if v})
        _write(data)
        text = message(event, data, after_pause)
        try:
            task = asyncio.get_running_loop().create_task(send_telegram(text))
        except RuntimeError:
            return
        _tasks.add(task)
        task.add_done_callback(_tasks.discard)
    except Exception as exc:  # журнал активности не должен мешать работе
        log.warning("Журнал активности: %s", exc)
