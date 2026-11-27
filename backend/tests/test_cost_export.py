"""Выгрузка расчёта стоимости в xlsx: листы по шаблону, формулы на месте и дают те же рубли, что журнал."""
from __future__ import annotations

import io
import re
import sqlite3

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook

from app import cost_export
from app import store as store_module
from app.agent.loop import STEP_LABELS
from app.config import get_settings
from app.store import Store

from .test_extras import turn

# Цены ProxyAPI для Claude Haiku 5.5 с НДС 5 %, ₽ за 1 млн токенов
IN, OUT, READ, WRITE = 30.0, 150.0, 3.0, 37.5
PRICES = cost_export.Prices(IN, OUT, READ, WRITE, "RUB", 0.0, 0.77, 0.05)
_CELL = re.compile(r"(?:'([^']+)'!)?\$?([A-Z]{1,3})\$?(\d+)(?::\$?([A-Z]{1,3})\$?(\d+))?")


def evaluator(wb):
    """Считает формулы листа сам: openpyxl их не вычисляет. Хватает того, что пишет выгрузка:
    арифметика, ссылки на ячейки и листы, SUM по столбцу, IF со сравнением."""
    cache: dict[tuple[str, str], float | str] = {}

    def value(sheet: str, ref: str):
        key = (sheet, ref)
        if key not in cache:
            raw = wb[sheet][ref].value
            cache[key] = calc(raw[1:], sheet) if isinstance(raw, str) and raw.startswith("=") else (raw or 0)
        return cache[key]

    def calc(expr: str, sheet: str):
        def cell(m: re.Match) -> str:
            name = m.group(1) or sheet
            if m.group(4):
                rows = range(int(m.group(3)), int(m.group(5)) + 1)
                return "[" + ",".join(f"v({name!r},'{m.group(2)}{r}')" for r in rows) + "]"
            return f"v({name!r},'{m.group(2)}{m.group(3)}')"

        code = _CELL.sub(cell, expr).replace("<>", "!=")
        code = re.sub(r"(?<![<>!=])=(?!=)", "==", code)
        return eval(code, {"v": value, "SUM": sum, "IF": lambda c, a, b: a if c else b})  # noqa: S307

    return value


def cost(inp: int, out: int, read: int, write: int) -> float:
    """Как agent.loop._cost: вход включает запись в кэш."""
    return ((inp - write) * IN + write * WRITE + out * OUT + read * READ) / 1_000_000


def seed(store: Store, monkeypatch, at: str, vehicle: str, author: str | None, calls: list[tuple], kind="answer",
         model="anthropic/claude-haiku-5-5", scenario: bool = True) -> int:
    monkeypatch.setattr(store_module, "now", lambda: at)
    turn_id = store.start_turn(vehicle, "S-1", author)
    for step, inp, out, read, write in calls:
        price = 0.0 if model.startswith("qwen") else cost(inp, out, read, write)  # локальная модель бесплатна
        store.log_llm_call(turn_id, STEP_LABELS[step], model, inp, out, read, price, 1000)
    store.finish_turn(turn_id, kind, 2000, scenario)
    return turn_id


@pytest.fixture
def journal(environment, monkeypatch):
    store = Store(get_settings().db_path)
    # Сценарий 1: вердикт (поиск и ответ), затем вопрос Иванова
    seed(store, monkeypatch, "2026-11-20T10:00:00+03:00", "A101TT77", None,
         [("tools", 8000, 300, 4000, 7000), ("answer", 5000, 2500, 11000, 1000)], kind="verdict")
    seed(store, monkeypatch, "2026-11-20T10:05:00+03:00", "A101TT77", "Иванов",
         [("tools", 9000, 250, 3000, 8000), ("answer", 6000, 2000, 10000, 0)], scenario=False)
    # Сценарий 2 на другой машине и в другой день, механик Петров, с заявкой
    seed(store, monkeypatch, "2026-11-26T21:10:00+03:00", "B202BB78", "Петров",
         [("tools", 8500, 280, 3500, 8400), ("ticket", 8600, 4500, 12000, 2000)], kind="ticket_draft")
    # Локальная модель в тот же день: цена 0
    seed(store, monkeypatch, "2026-11-26T22:00:00+03:00", "B202BB78", "Петров",
         [("tools", 1000, 100, 0, 0)], model="qwen2.5:7b")
    monkeypatch.setattr(store_module, "now", lambda: "2026-11-27T12:00:00+03:00")
    store.log_stt("gpt-4o-mini-transcribe", 6.0, 0.0, 1200)
    store.log_stt("gpt-4o-mini-transcribe", 9.0, 0.0, 1300)
    return store


@pytest.fixture
def client(environment, monkeypatch):
    monkeypatch.setenv("PRICE_INPUT_PER_MTOK", str(IN))
    monkeypatch.setenv("PRICE_OUTPUT_PER_MTOK", str(OUT))
    monkeypatch.setenv("PRICE_CACHE_READ_PER_MTOK", str(READ))
    monkeypatch.setenv("PRICE_CACHE_WRITE_PER_MTOK", str(WRITE))
    monkeypatch.setenv("PRICE_CURRENCY", "RUB")
    monkeypatch.setenv("STT_PRICE_PER_MIN", "0.77")
    get_settings.cache_clear()
    from app import main

    with TestClient(main.app) as test_client:
        yield test_client


def download(client, **params):
    response = client.get("/api/usage/export.xlsx", params=params)
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    assert "attachment" in response.headers["content-disposition"]
    return load_workbook(io.BytesIO(response.content))


def call_rows(wb) -> list[tuple]:
    return [row for row in wb["Вызовы"].iter_rows(min_row=2, values_only=True) if row[0]]


def test_export_has_template_sheets_and_formulas(journal, client):
    wb = download(client)
    assert wb.sheetnames == list(cost_export.SHEETS)
    ws = wb["На 1 запрос"]
    headers = [ws.cell(row=10, column=c).value for c in range(1, 10)]
    assert headers == ["Шаг агента", "Модель", "Вызовов на запрос", "Токенов на входе", "Токенов на выходе",
                       "Цена входа за 1 млн", "Цена выхода за 1 млн", "Валюта ($ или ₽)", "₽ на 1 запрос"]
    steps = [ws.cell(row=r, column=1).value for r in range(11, 20)]
    for label in STEP_LABELS.values():
        assert label in steps, f"нет строки шага «{label}»"
    assert all(str(ws.cell(row=r, column=9).value).startswith("=") for r in range(11, 11 + 5))
    total = next(r for r in range(11, 30) if ws.cell(row=r, column=1).value == "Итого модели на 1 запрос")
    assert ws.cell(row=total, column=9).value.startswith("=SUM(")
    assert any("Распознавание речи" == ws.cell(row=r, column=1).value for r in range(total, total + 12))
    assert ws["B7"].value == pytest.approx(0.05), "по умолчанию для цен в рублях вычитается НДС 5 %"
    assert ws["B7"].fill.fgColor.rgb.endswith("FFF2CC"), "ячейки ввода светло-жёлтые"
    assert ws.cell(row=10, column=1).font.bold

    fleet = wb["Пересчёт на парк"]
    assert [fleet.cell(row=r, column=1).value for r in range(29, 33)] == [50, 150, 370, 800]
    assert all(str(fleet.cell(row=r, column=6).value).startswith("=") for r in range(29, 33))
    assert wb["Индексация и стенд"]["B8"].value == 0, "индексация без токенов модели"
    assert len(call_rows(wb)) == 7


def test_formulas_give_journal_cost_without_vat(journal, client):
    wb = download(client, model="anthropic/claude-haiku-5-5")
    value = evaluator(wb)
    ws = wb["На 1 запрос"]
    total = next(r for r in range(11, 30) if ws.cell(row=r, column=1).value == "Итого модели на 1 запрос")

    calls = journal.llm_calls(model="anthropic/claude-haiku-5-5")
    logged = sum(c["cost_rub"] for c in calls) / 2  # два сценария
    assert value("На 1 запрос", f"I{total}") == pytest.approx(logged / 1.05, rel=1e-4)
    assert value("На 1 запрос", f"N{total}") == pytest.approx(logged / 1.05, rel=1e-9)
    for r in range(11, total):  # по каждому шагу формула совпадает с журналом
        assert value("На 1 запрос", f"I{r}") == pytest.approx(value("На 1 запрос", f"N{r}"), rel=1e-3, abs=1e-6)

    # Вопрос — средний ход с ответом; голос — 7,5 с на запись по 0,77 ₽ за минуту с НДС
    question = sum(c["cost_rub"] for c in calls if c["kind"] == "answer") / 1.05
    q_row = next(r for r in range(total, total + 20) if str(ws.cell(row=r, column=1).value).startswith("Отдельный"))
    assert value("На 1 запрос", f"I{q_row}") == pytest.approx(question, rel=1e-9)
    record = 7.5 / 60 * 0.77 / 1.05

    fleet = "Пересчёт на парк"
    scenario = logged / 1.05
    assert value(fleet, "B13") == pytest.approx(record)
    assert value(fleet, "B21") == pytest.approx(50 * 4.3 * (scenario + 3 * question), rel=1e-4)
    assert value(fleet, "B22") == pytest.approx(50 * 4.3 * 4 * record, rel=1e-6)
    for r, cars in zip(range(29, 33), (50, 150, 370, 800)):
        expected = cars * 4.3 * (scenario + 3 * question + 4 * record)
        assert value(fleet, f"F{r}") == pytest.approx(expected, rel=1e-4)
        assert value(fleet, f"G{r}") == pytest.approx(expected / cars, rel=1e-4)
    assert value("Индексация и стенд", "B30") == 0


def test_filters_narrow_calls_sheet(journal, client):
    assert {r[1] for r in call_rows(download(client, vehicle_id="A101TT77"))} == {"A101TT77"}
    assert {r[2] for r in call_rows(download(client, mechanic="Петров"))} == {"Петров"}
    assert len(call_rows(download(client, mechanic="Иванов"))) == 2
    assert {r[7] for r in call_rows(download(client, model="qwen2.5:7b"))} == {"qwen2.5:7b"}
    by_day = call_rows(download(client, **{"from": "2026-11-26", "to": "2026-11-26"}))
    assert len(by_day) == 3 and all(r[0].startswith("2026-11-26") for r in by_day)
    assert len(call_rows(download(client, to="2026-11-20T10:00"))) == 2, "конец периода включает всю минуту"
    assert call_rows(download(client, vehicle_id="нет-такой")) == []


def test_local_model_is_priced_zero(journal, client):
    wb = download(client, model="qwen2.5:7b")
    value = evaluator(wb)
    ws = wb["На 1 запрос"]
    assert ws["F11"].value == 0 and value("На 1 запрос", "I11") == 0


def test_bad_date_is_rejected(client):
    response = client.get("/api/usage/export.xlsx", params={"from": "вчера"})
    assert response.status_code == 400 and "ГГГГ-ММ-ДД" in response.json()["detail"]


def test_empty_journal_still_exports(client):
    wb = download(client)
    assert wb.sheetnames == list(cost_export.SHEETS) and call_rows(wb) == []


def test_cache_write_is_recovered_from_logged_cost():
    call = {"input_tokens": 8000, "output_tokens": 300, "cache_read_tokens": 4000, "cost_rub": cost(8000, 300, 4000, 7000)}
    assert PRICES.cache_write_tokens(call) == 7000
    assert PRICES.cache_write_tokens({**call, "cost_rub": 0.0}) == 0


async def test_turn_records_mechanic(environment, index, services):
    store = Store(get_settings().db_path)
    await turn(store, index, "A101TT77", "S-9003", "Какое давление масла должно быть?",
               profile={"level": "expert", "name": "Иванов"})
    calls = store.llm_calls(mechanic="Иванов")
    assert calls and {c["author"] for c in calls} == {"Иванов"}


def test_old_database_gets_author_column(tmp_path):
    path = tmp_path / "old.sqlite"
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE turns (id INTEGER PRIMARY KEY AUTOINCREMENT, vehicle_id TEXT NOT NULL, session_id TEXT, "
               "scenario_id INTEGER, kind TEXT, duration_ms INTEGER, created_at TEXT NOT NULL)")
    db.execute("INSERT INTO turns (vehicle_id, created_at) VALUES ('A', '2026-11-01T00:00:00+00:00')")
    db.commit()
    db.close()
    store = Store(path)
    assert store.start_turn("A", "S", "Иванов") == 2
    store.close()
