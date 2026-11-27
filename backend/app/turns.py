"""Ходы агента в фоне.

Ход живёт на сервере и не зависит от соединения, которое его начало: механик ушёл со страницы,
погас экран телефона или пропала связь — агент доработает, ответ ляжет в переписку.
Вернувшись, интерфейс подключается к ходу и получает его события с начала.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable

log = logging.getLogger("mechanic")
Emit = Callable[[dict], Awaitable[None]]


class Turn:
    """События одного хода. Читателей может быть несколько, каждый получает всё с начала."""

    def __init__(self) -> None:
        self.events: list[dict] = []
        self.finished = False
        self.failed = False
        self._wake = asyncio.Event()

    @classmethod
    def empty(cls) -> Turn:
        """Хода нет: читатель сразу получает конец потока."""
        turn = cls()
        turn.finished = True
        return turn

    def _notify(self) -> None:
        self._wake.set()
        self._wake = asyncio.Event()

    async def emit(self, event: dict) -> None:
        if event.get("type") == "error":
            self.failed = True
        self.events.append(event)
        self._notify()

    def finish(self) -> None:
        self.finished = True
        self._notify()

    async def follow(self) -> AsyncIterator[dict]:
        sent = 0
        while True:
            wake = self._wake
            if sent < len(self.events):
                event = self.events[sent]
                sent += 1
                yield event
            elif self.finished:
                return
            else:
                await wake.wait()


# В реестре лежат идущие ходы и ходы со сбоем, о котором механик ещё не узнал:
# без этого он вернулся бы к вопросу без ответа и без объяснения.
_turns: dict[str, Turn] = {}
_tasks: set[asyncio.Task] = set()


def get(vehicle_id: str) -> Turn | None:
    return _turns.get(vehicle_id)


def status(vehicle_id: str) -> str | None:
    """running — агент ещё работает; failed — ход оборвался, ошибку механик ещё не видел; None — хода нет."""
    turn = _turns.get(vehicle_id)
    if turn is None:
        return None
    return "failed" if turn.finished else "running"


def start(vehicle_id: str, work: Callable[[Emit], Awaitable[None]]) -> Turn | None:
    """Запускает ход в фоне. None, если по машине уже идёт ход."""
    if status(vehicle_id) == "running":
        return None
    turn = Turn()
    _turns[vehicle_id] = turn

    async def run() -> None:
        try:
            await work(turn.emit)
        except Exception:
            log.exception("Сбой хода агента")
            await turn.emit({"type": "error", "text": "Внутренняя ошибка сервера. Повторите запрос."})
            await turn.emit({"type": "done", "usage": {}})
        finally:
            turn.finish()
            if not turn.failed:
                _forget(vehicle_id, turn)

    task = asyncio.create_task(run())
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return turn


def seen(vehicle_id: str) -> None:
    """Механик увидел ошибку хода. Об этом сообщает страница: дочитанный поток ничего не доказывает,
    прокси дочитывает его и после ухода механика."""
    turn = _turns.get(vehicle_id)
    if turn is not None and turn.finished:
        del _turns[vehicle_id]


def _forget(vehicle_id: str, turn: Turn) -> None:
    if _turns.get(vehicle_id) is turn:
        del _turns[vehicle_id]


async def shutdown() -> None:
    tasks = list(_tasks)
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    _turns.clear()
