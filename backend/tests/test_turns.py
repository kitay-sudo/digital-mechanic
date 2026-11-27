"""Ход агента идёт в фоне и не зависит от соединения, которое его начало."""
from __future__ import annotations

import asyncio

import pytest

from app import turns


@pytest.fixture(autouse=True)
async def clean():
    yield
    await turns.shutdown()


async def read(vehicle_id: str) -> list[str]:
    turn = turns.get(vehicle_id) or turns.Turn.empty()
    return [event["type"] async for event in turn.follow()]


async def test_turn_finishes_after_the_reader_left():
    gate, done = asyncio.Event(), []

    async def work(emit):
        await emit({"type": "user"})
        await gate.wait()
        await emit({"type": "message"})
        await emit({"type": "done"})
        done.append(True)

    turn = turns.start("A1", work)
    reader = turn.follow()
    assert (await anext(reader))["type"] == "user"
    await reader.aclose()  # механик ушёл со страницы

    assert turns.status("A1") == "running"
    assert turns.start("A1", work) is None  # второй ход по той же машине не начинается

    # Вернулся: события приходят с начала хода и до конца
    back = asyncio.create_task(read("A1"))
    await asyncio.sleep(0)
    gate.set()
    assert await back == ["user", "message", "done"]
    assert done and turns.status("A1") is None


async def test_failed_turn_waits_until_the_page_shows_the_error():
    async def work(emit):
        await emit({"type": "user"})
        raise RuntimeError("сбой")

    turns.start("A1", work)
    await asyncio.sleep(0.01)
    # Поток могли дочитать и без механика (прокси), поэтому ошибка ждёт, пока страница её не покажет
    assert await read("A1") == ["user", "error", "done"]
    assert turns.status("A1") == "failed"
    assert await read("A1") == ["user", "error", "done"]
    turns.seen("A1")
    assert turns.status("A1") is None
    assert await read("A1") == []


async def test_new_turn_replaces_unread_failure():
    async def bad(emit):
        raise RuntimeError("сбой")

    async def good(emit):
        await emit({"type": "done"})

    turns.start("A1", bad)
    await asyncio.sleep(0.01)
    turn = turns.start("A1", good)
    assert turn is not None
    assert [e["type"] async for e in turn.follow()] == ["done"]
    assert turns.status("A1") is None
