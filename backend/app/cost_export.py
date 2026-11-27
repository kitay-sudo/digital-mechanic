"""Выгрузка расчёта стоимости в xlsx по шаблону организаторов («калькулятор экономики решения»).

Лист «На 1 запрос» повторяет таблицу шаблона: строка на каждый шаг агента, который вызывает модель, рубли
считает формула Excel. Дальше листы «Пересчёт на парк», «Индексация и стенд» и «Вызовы» (сырые строки журнала).

Запрос — сценарий по машине, как его пишет журнал (Store.finish_turn): от результата диагностики до ответа
механику или заявки. «Вызовов на запрос» — среднее на сценарий за выбранный период.

Запись в кэш подсказки журнал отдельно не хранит: входные токены вызова включают её, а стоимость вызова посчитана
по ценам настроек (agent.loop._cost). Поэтому доля записи выводится из записанной стоимости по тем же ценам.
Если цены в настройках меняли после прогона, этот вывод неточен.

Файл сдачи docs/cost-calculation.xlsx собран из папки backend по архиву стенда (третий прогон 26.11: сценарии
защиты и отдельно 21 контрольный вопрос), цены ProxyAPI с НДС 5 %. Одной командой, аргументы по строкам:
    uv run python -m app.cost_export
        --db ../data/archive/stand-20261127-1918/app.sqlite --out ../docs/cost-calculation.xlsx
        --model anthropic/claude-haiku-5-5 --from 2026-11-26T21:09:39 --to 2026-11-26T21:17:44
        --questions-from 2026-11-26T21:17:45 --questions-to 2026-11-26T21:21:59
        --prices 30,150,3,37.5 --currency RUB --vat 5 --stt-price 0.77
        --source "proxyapi.ru/models/anthropic/claude-haiku-5-5 на 27.11.2026"
        --kb ../knowledge/index.sqlite --index-seconds 128
"""
from __future__ import annotations

import argparse
import io
import re
import shutil
import sqlite3
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from .agent.loop import STEP_LABELS
from .config import Settings
from .store import Store

STEP_ORDER = [STEP_LABELS[k] for k in ("tools", "answer", "ticket", "retry")]
SHEETS = ("На 1 запрос", "Пересчёт на парк", "Индексация и стенд", "Вызовы")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}(T\d{2}(:\d{2}(:\d{2})?)?)?$")

# Оформление: жёлтые ячейки заполняет команда, как в шаблоне организаторов
INPUT = PatternFill("solid", fgColor="FFF2CC")
HEAD = PatternFill("solid", fgColor="E7E6E6")
BOLD = Font(bold=True)
TITLE = Font(bold=True, size=14)
NOTE = Font(italic=True, color="595959")
THIN = Side(style="thin", color="BFBFBF")
BOX = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
WRAP = Alignment(wrap_text=True, vertical="top")
RUB = "#,##0.00"
INT = "#,##0"
PCT = "0%"


@dataclass(frozen=True)
class Filters:
    date_from: str | None = None
    date_to: str | None = None
    model: str | None = None
    vehicle_id: str | None = None
    mechanic: str | None = None

    def __post_init__(self):
        for value in (self.date_from, self.date_to):
            if value and not _DATE.match(value):
                raise ValueError(f"Неверная дата «{value}»: нужен формат ГГГГ-ММ-ДД или ГГГГ-ММ-ДДTЧЧ:ММ:СС")

    def describe(self) -> str:
        parts = []
        if self.date_from or self.date_to:
            parts.append(f"период {self.date_from or 'с начала журнала'} — {self.date_to or 'по сей день'}")
        for label, value in (("модель", self.model), ("машина", self.vehicle_id), ("механик", self.mechanic)):
            if value:
                parts.append(f"{label} {value}")
        return ", ".join(parts) or "весь журнал"


@dataclass(frozen=True)
class Prices:
    """Цены как в прайсе поставщика (из настроек сервера) и НДС, который в них включён (доля, 0,05 = 5 %)."""
    input: float
    output: float
    cache_read: float
    cache_write: float
    currency: str = "RUB"
    usd_rate: float = 0.0
    stt_per_min: float = 0.0
    vat: float = 0.0
    source: str = ""

    @classmethod
    def from_settings(cls, settings: Settings, vat: float | None = None) -> Prices:
        # Цены ProxyAPI в рублях включают НДС 5 %, цены Anthropic в долларах — без НДС
        default_vat = 0.05 if settings.price_currency == "RUB" else 0.0
        return cls(settings.price_input, settings.price_output, settings.price_cache_read, settings.price_cache_write,
                   settings.price_currency, settings.usd_rate, settings.stt_price_per_min,
                   default_vat if vat is None else vat)

    @property
    def symbol(self) -> str:
        return "$" if self.currency == "USD" else "₽"

    def cache_write_tokens(self, call: dict) -> int:
        """Сколько входных токенов вызова записано в кэш: из стоимости вызова, посчитанной по этим ценам."""
        premium = self.cache_write - self.input
        cost = call["cost_rub"]
        if self.currency == "USD":
            cost = cost / self.usd_rate if self.usd_rate else 0.0
        if premium <= 0 or cost <= 0:
            return 0
        base = (call["input_tokens"] * self.input + call["output_tokens"] * self.output
                + call["cache_read_tokens"] * self.cache_read) / 1_000_000
        written = round((cost - base) * 1_000_000 / premium)
        return min(max(written, 0), call["input_tokens"])


@dataclass
class Step:
    step: str
    model: str
    calls: int = 0
    per_scenario: float = 0.0
    input: float = 0.0
    output: float = 0.0
    cache_read: float = 0.0
    cache_write: float = 0.0
    logged_rub: float = 0.0  # по журналу, на сценарий, в ценах настроек
    paid: bool = False


@dataclass
class Measurement:
    calls: list[dict]
    scenarios: int
    turns: int
    steps: list[Step]
    question_rub: float
    question_basis: str
    stt_seconds: float
    stt_basis: str
    models: list[str] = field(default_factory=list)

    @property
    def turns_per_scenario(self) -> float:
        return self.turns / self.scenarios if self.scenarios else 0.0


def _turn_costs(calls: list[dict]) -> dict[int, float]:
    costs: dict[int, float] = {}
    for c in calls:
        costs[c["turn_id"]] = costs.get(c["turn_id"], 0.0) + c["cost_rub"]
    return costs


def _question(calls: list[dict], where: str) -> tuple[float, str]:
    """Отдельный вопрос механика: средняя стоимость хода с ответом на вопрос (не вердикт и не заявка)."""
    costs = _turn_costs(calls)
    answers = {c["turn_id"] for c in calls if c["kind"] == "answer"}
    if answers:
        average = sum(costs[t] for t in answers) / len(answers)
        return average, f"среднее по {len(answers)} ходам с ответом на вопрос{where}"
    average = sum(costs.values()) / len(costs) if costs else 0.0
    return average, f"ходов с ответом на вопрос нет, взято среднее по {len(costs)} ходам{where}"


def measure(calls: list[dict], stt_period: list[dict], stt_all: list[dict], prices: Prices,
            question_calls: list[dict] | None = None, question_where: str = "") -> Measurement:
    """Средние на сценарий по вызовам из журнала. Ход без сценария (ещё идёт) в средние не входит.

    question_calls: вызовы, по которым считать отдельный вопрос, если не по тем же (например, прогон
    контрольных вопросов отдельно от прогона сценариев).
    """
    done = [c for c in calls if c["scenario_id"] is not None]
    scenarios = len({c["scenario_id"] for c in done})
    n = scenarios or 1
    groups: dict[tuple[str, str], list[dict]] = {}
    for c in done:
        groups.setdefault((c["step"], c["model"]), []).append(c)
    models = sorted({c["model"] for c in done})
    steps = []
    for (step, model), rows in groups.items():
        k = len(rows)
        steps.append(Step(
            step=step, model=model, calls=k, per_scenario=k / n,
            input=sum(r["input_tokens"] for r in rows) / k, output=sum(r["output_tokens"] for r in rows) / k,
            cache_read=sum(r["cache_read_tokens"] for r in rows) / k,
            cache_write=sum(prices.cache_write_tokens(r) for r in rows) / k,
            logged_rub=sum(r["cost_rub"] for r in rows) / n, paid=any(r["cost_rub"] > 0 for r in rows),
        ))
    present = {s.step for s in steps}
    for step in STEP_ORDER:  # шаг без вызовов за период тоже показываем: в шаблоне строка на каждый шаг
        if step not in present:
            steps.append(Step(step=step, model=models[0] if len(models) == 1 else "—",
                              paid=len(models) == 1 and any(s.paid for s in steps)))
    rank = {name: i for i, name in enumerate(STEP_ORDER)}
    steps.sort(key=lambda s: (rank.get(s.step, len(rank)), s.model))

    asked = done if question_calls is None else [c for c in question_calls if c["scenario_id"] is not None]
    question_rub, basis = _question(asked, question_where)

    stt, stt_basis = stt_period, f"среднее по записям за период ({len(stt_period)})"
    if not stt and stt_all:
        stt, stt_basis = stt_all, f"за период записей нет, среднее по всем записям журнала ({len(stt_all)})"
    seconds = sum(r["seconds"] for r in stt) / len(stt) if stt else 0.0
    return Measurement(calls=calls, scenarios=scenarios, turns=len(_turn_costs(done)), steps=steps,
                       question_rub=question_rub, question_basis=basis, stt_seconds=seconds,
                       stt_basis=stt_basis if stt else "записей голоса в журнале нет", models=models)


@dataclass
class Info:
    """Что не из журнала вызовов: база знаний, стенд, модель распознавания, подписи."""
    filters: Filters = field(default_factory=Filters)
    stt_model: str = "gpt-4o-mini-transcribe"
    kb: dict = field(default_factory=dict)
    index_seconds: float | None = None  # пусто — впишут вручную
    vps_rub: float | None = None
    generated: str = ""


def _num(value: float) -> str:
    """Число для формулы Excel: точка как разделитель, без лишних нулей."""
    return repr(round(float(value), 6)).removesuffix(".0")


def _ru(value: float, digits: int = 2) -> str:
    """Число для текста: запятая как разделитель, без лишних нулей."""
    text = f"{value:.{digits}f}".rstrip("0").rstrip(".") if digits else f"{value:.0f}"
    return text.replace(".", ",")


def _style(cell, *, fmt: str | None = None, fill=None, font=None, box=True, wrap=False):
    if fmt:
        cell.number_format = fmt
    if fill:
        cell.fill = fill
    if font:
        cell.font = font
    if box:
        cell.border = BOX
    if wrap:
        cell.alignment = WRAP


def _widths(ws, widths: dict[str, float]) -> None:
    for col, width in widths.items():
        ws.column_dimensions[col].width = width


def _header(ws, row: int, titles: list[str], start: int = 1) -> None:
    for i, title in enumerate(titles):
        cell = ws.cell(row=row, column=start + i, value=title)
        _style(cell, fill=HEAD, font=BOLD, wrap=True)
    ws.row_dimensions[row].height = 45


def _note(ws, row: int, text: str, column: int = 1, end: int | None = None) -> None:
    cell = ws.cell(row=row, column=column, value=text)
    cell.font = NOTE
    if end:
        # Excel не подбирает высоту объединённой ячейки сам: длинной заметке нужна вторая строка
        ws.merge_cells(start_row=row, start_column=column, end_row=row, end_column=end)
        cell.alignment = WRAP
        if len(text) > 110:
            ws.row_dimensions[row].height = 30


def _sheet_request(ws, m: Measurement, p: Prices, info: Info) -> dict[str, str]:
    """Лист 1 по шаблону. Возвращает адреса ячеек, на которые ссылаются другие листы."""
    vat = "$B$7"
    ws["A1"] = "Цифровой механик: стоимость одного запроса"
    ws["A1"].font = TITLE
    _note(ws, 2, "Запрос — сценарий по машине: от результата диагностики до ответа механику или заявки. "
                 "Все суммы в рублях без НДС.", end=9)
    period = f"{m.calls[0]['created_at']} — {m.calls[-1]['created_at']}" if m.calls else "вызовов нет"
    _note(ws, 3, f"Замер по журналу сервера: {period}; сценариев {m.scenarios}, ходов {m.turns}, "
                 f"вызовов модели {sum(s.calls for s in m.steps)}. Отбор: {info.filters.describe()}.", end=9)
    _note(ws, 4, f"Выгружено {info.generated}.", end=9)

    ws["A6"] = "Курс доллара ЦБ РФ на 26.11.2026, ₽ за 1 $"
    ws["B6"] = p.usd_rate
    _style(ws["B6"], fmt=RUB, fill=INPUT)
    ws["C6"] = "нужен, если цена модели в $" + ("; цены в настройках в ₽, курс не используется"
                                               if p.currency != "USD" else "")
    ws["A7"] = "НДС, включённый в цены настроек"
    ws["B7"] = p.vat
    _style(ws["B7"], fmt="0.0%", fill=INPUT)
    ws["C7"] = "цены в таблице без НДС: цена из настроек ÷ (1 + НДС)"
    for ref in ("C6", "C7"):
        ws[ref].font = NOTE

    ws["A9"] = "Модели на один запрос"
    ws["A9"].font = BOLD
    ws["J9"] = "Уточнение к входу: кэш подсказки"
    ws["J9"].font = BOLD
    ws["N9"] = "Сверка"
    ws["N9"].font = BOLD
    _header(ws, 10, ["Шаг агента", "Модель", "Вызовов на запрос", "Токенов на входе", "Токенов на выходе",
                     "Цена входа за 1 млн", "Цена выхода за 1 млн", "Валюта ($ или ₽)", "₽ на 1 запрос",
                     "Чтение из кэша, токенов (сверх входа)", "Из входа записано в кэш, токенов",
                     "Цена чтения кэша за 1 млн", "Цена записи в кэш за 1 млн", "₽ на 1 запрос по журналу"])
    first = row = 11
    for s in m.steps:
        price = (lambda value: f"={_num(value)}/(1+{vat})") if s.paid else (lambda value: 0)
        values = [s.step, s.model, round(s.per_scenario, 4), round(s.input), round(s.output),
                  price(p.input), price(p.output), p.symbol,
                  f"=C{row}*((D{row}-K{row})*F{row}+K{row}*M{row}+J{row}*L{row}+E{row}*G{row})/1000000"
                  f"*IF(H{row}=\"$\",$B$6,1)",
                  round(s.cache_read), round(s.cache_write), price(p.cache_read), price(p.cache_write),
                  f"={_num(s.logged_rub)}/(1+{vat})"]
        formats = [None, None, "0.00", INT, INT, RUB, RUB, None, RUB, INT, INT, RUB, RUB, RUB]
        for col, (value, fmt) in enumerate(zip(values, formats), start=1):
            cell = ws.cell(row=row, column=col, value=value)
            _style(cell, fmt=fmt, fill=None if col in (9, 14) else INPUT)
        row += 1
    total = row
    ws.cell(row=total, column=1, value="Итого модели на 1 запрос").font = BOLD
    for col in (9, 14):
        letter = get_column_letter(col)
        cell = ws.cell(row=total, column=col, value=f"=SUM({letter}{first}:{letter}{total - 1})")
        _style(cell, fmt=RUB, font=BOLD)

    ws.cell(row=total + 2, column=1, value="Комментарий").font = BOLD
    priced = [s for s in m.steps if s.paid]
    lines = [
        f"Вызовы и токены — средние на сценарий по журналу сервера ({m.scenarios} сценариев, в среднем "
        f"{_ru(m.turns_per_scenario)} хода: вердикт и вопросы механика). Модель: {', '.join(m.models) or 'нет вызовов'}.",
        (f"Цены из настроек за 1 млн токенов: вход {_ru(p.input)}, выход {_ru(p.output)}, чтение кэша "
         f"{_ru(p.cache_read)}, запись в кэш {_ru(p.cache_write)} {p.symbol}, НДС {_ru(p.vat * 100, 1)} % вычтен. "
         f"Запись в кэш выведена из стоимости вызовов в журнале.{' Прайс: ' + p.source + '.' if p.source else ''}")
        if priced else "Платных вызовов за период нет: локальная модель или заглушка, цена токенов 0.",
        "Поиск по руководствам — SQLite FTS5 без модели и эмбеддингов, 0 ₽; своих серверов с GPU нет. "
        "Растёт с числом вопросов механика (до 50 в сложном ремонте), фото узла и заявкой.",
    ]
    for i, text in enumerate(lines):
        r = total + 3 + i
        cell = ws.cell(row=r, column=1, value=text)
        ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=9)
        _style(cell, fill=INPUT, wrap=True)
        ws.row_dimensions[r].height = 32

    stt = total + 7
    ws.cell(row=stt, column=1, value="Распознавание речи (голос механика)").font = BOLD
    _header(ws, stt + 1, ["Шаг агента", "Модель", "Записей на запрос", "Секунд на запись", "",
                          "Цена за 1 минуту", "", "Валюта ($ или ₽)", "₽ на 1 запрос"])
    r = stt + 2
    stt_price = f"={_num(p.stt_per_min)}/(1+{vat})" if p.stt_per_min else 0
    values = {1: "Распознавание речи", 2: info.stt_model, 3: round(m.turns_per_scenario, 4),
              4: round(m.stt_seconds, 3), 6: stt_price, 8: "₽", 9: f"=C{r}*D{r}/60*F{r}"}
    for col, value in values.items():
        cell = ws.cell(row=r, column=col, value=value)
        _style(cell, fmt={3: "0.00", 4: "0.0", 6: RUB, 9: RUB}.get(col), fill=None if col == 9 else INPUT)
    _note(ws, r + 1, f"Записей на запрос — допущение: каждое сообщение механика голосом. Длина записи: {m.stt_basis}."
          + ("" if p.stt_per_min else " Цена не задана (STT_PRICE_PER_MIN), впишите по прайсу."), end=9)

    r_total = stt + 4
    ws.cell(row=r_total, column=1, value="Итого на 1 запрос с голосовым вводом").font = BOLD
    _style(ws.cell(row=r_total, column=9, value=f"=I{total}+I{stt + 2}"), fmt=RUB, font=BOLD)
    r_q = r_total + 1
    ws.cell(row=r_q, column=1, value="Отдельный вопрос механика в чате (для пересчёта на парк)")
    _style(ws.cell(row=r_q, column=9, value=f"={_num(m.question_rub)}/(1+{vat})"), fmt=RUB)
    _note(ws, r_q, f"по журналу: {m.question_basis}", column=10)
    for ref in (f"A{r_q}",):
        ws[ref].alignment = WRAP

    _widths(ws, {"A": 34, "B": 28, **{c: 13 for c in "CDEFGHI"}, **{c: 15 for c in "JKLMN"}})
    return {"total": f"I{total}", "question": f"I{r_q}", "stt_seconds": f"D{r}", "stt_price": f"F{r}",
            "turns": _ru(m.turns_per_scenario)}


def _sheet_fleet(ws, refs: dict[str, str], stand: dict[str, str]) -> None:
    src = f"'{SHEETS[0]}'!"
    ws["A1"] = "Пересчёт на парк"
    ws["A1"].font = TITLE
    _note(ws, 2, "Процедура по машине: результат проверки и вопросы механика до решения. Жёлтые ячейки можно менять.",
          end=7)
    _header(ws, 4, ["Ввод", "Значение", "Допущение"])
    inputs = [
        ("Машин в парке", 50, INT, "пример ментора — 50 машин; сценарии ниже — 50, 150, 370, 800"),
        ("Проверок в месяц на машину", 4.3, "0.0", "раз в неделю: 52 ÷ 12; при проверке раз в две недели — 2,15"),
        ("Вопросов механика на процедуру", 4, INT, "заказчик: обычно 3–5, в сложном ремонте до 50"),
        ("Доля проверок с отклонением", 1, PCT, "консервативно: каждая проверка разбирается с механиком"),
        ("Доля сообщений голосом", 1, PCT, "верхняя граница: все сообщения голосом"),
        ("Стоимость сценария, ₽", f"={src}{refs['total']}", RUB,
         f"лист 1: результат диагностики и ответы сценария, в замере в среднем {refs['turns']} хода"),
        ("Стоимость отдельного вопроса, ₽", f"={src}{refs['question']}", RUB, "лист 1: средний ход с ответом"),
        ("Проверка без отклонения, ₽", "=B11", RUB, "одна реплика: «результат в норме»"),
        ("Распознавание одной записи, ₽", f"={src}{refs['stt_seconds']}/60*{src}{refs['stt_price']}", RUB,
         "лист 1: длина записи × цена минуты"),
        ("Сервер продукта, ₽ в месяц", f"='{SHEETS[2]}'!{stand['vps']}", RUB, "лист «Индексация и стенд»"),
    ]
    for i, (label, value, fmt, note) in enumerate(inputs):
        r = 5 + i
        ws.cell(row=r, column=1, value=label)
        _style(ws.cell(row=r, column=2, value=value), fmt=fmt, fill=INPUT)
        ws.cell(row=r, column=3, value=note).font = NOTE

    _header(ws, 16, ["Расчёт", "₽", "Формула"])
    calc = [
        ("Процедура с отклонением: модель, ₽", "=B10+(B7-1)*B11", RUB,
         "сценарий + (вопросов − 1) × вопрос; с запасом: часть вопросов уже в сценарии"),
        ("Средняя проверка: модель, ₽", "=B8*B17+(1-B8)*B12", RUB, "по доле проверок с отклонением"),
        ("Средняя проверка: голос, ₽", "=(B8*B7+(1-B8))*B9*B13", RUB, "сообщений × доля голосом × запись"),
        ("Проверок в месяц на парк", "=B5*B6", "#,##0.0", "машин × проверок"),
        ("Модель в месяц на парк, ₽", "=B20*B18", RUB, ""),
        ("Голос в месяц на парк, ₽", "=B20*B19", RUB, ""),
        ("Итого в месяц на парк без сервера, ₽", "=B21+B22", RUB, ""),
        ("На машину в месяц без сервера, ₽", "=B6*(B18+B19)", RUB, ""),
        ("Итого в месяц на парк с сервером, ₽", "=B23+B14", RUB, ""),
    ]
    for i, (label, value, fmt, note) in enumerate(calc):
        r = 17 + i
        ws.cell(row=r, column=1, value=label)
        _style(ws.cell(row=r, column=2, value=value), fmt=fmt, font=BOLD if r in (23, 25) else None)
        ws.cell(row=r, column=3, value=note).font = NOTE

    ws["A27"] = "Сценарии по размеру парка"
    ws["A27"].font = BOLD
    _header(ws, 28, ["Машин", "Проверок в месяц", "Модель, ₽ в месяц", "Голос, ₽ в месяц", "Сервер, ₽ в месяц",
                     "Итого, ₽ в месяц", "На машину, ₽ в месяц"])
    for i, cars in enumerate((50, 150, 370, 800)):
        r = 29 + i
        row = [cars, f"=A{r}*$B$6", f"=B{r}*$B$18", f"=B{r}*$B$19", "=$B$14", f"=C{r}+D{r}+E{r}", f"=F{r}/A{r}"]
        for col, value in enumerate(row, start=1):
            _style(ws.cell(row=r, column=col, value=value), fmt=INT if col == 1 else ("#,##0.0" if col == 2 else RUB),
                   fill=INPUT if col == 1 else None)

    ws["A34"] = "Допущения"
    ws["A34"].font = BOLD
    notes = [
        "Токены оплачивает владелец платформы, подписка считается от числа машин: здесь только переменные затраты.",
        "Круглосуточная нагрузка не нужна: единицы запросов в час, один сервер продукта на весь парк.",
        "Стоимость сценария и вопроса — замер на демо (лист 1); фото узла и заявка удорожают ход.",
        "Если отклонение только в части проверок, уменьшите долю в B8: проверка без отклонения стоит как один вопрос.",
    ]
    for i, text in enumerate(notes):
        _note(ws, 35 + i, text, end=7)
    _widths(ws, {"A": 40, "B": 16, "C": 18, "D": 16, "E": 16, "F": 16, "G": 18})


def _sheet_stand(ws, info: Info) -> dict[str, str]:
    ws["A1"] = "Индексация и стенд"
    ws["A1"].font = TITLE
    kb = info.kb or {}

    def block(start: int, title: str, rows: list[tuple]) -> None:
        ws.cell(row=start, column=1, value=title).font = BOLD
        _header(ws, start + 1, ["Показатель", "Значение", "Комментарий"])
        for i, (label, value, fmt, note, editable) in enumerate(rows):
            r = start + 2 + i
            ws.cell(row=r, column=1, value=label)
            _style(ws.cell(row=r, column=2, value=value), fmt=fmt, fill=INPUT if editable else None)
            cell = ws.cell(row=r, column=3, value=note)
            cell.font = NOTE
            cell.alignment = WRAP

    block(3, "Разовая индексация руководств", [
        ("Руководств (PDF)", kb.get("manuals", 0), INT, "база знаний стенда", False),
        ("Страниц", kb.get("pages", 0), INT, f"из них без текстового слоя, распознано Tesseract: {kb.get('ocr_pages', 0)}",
         False),
        ("Фрагментов в индексе", kb.get("chunks", 0), INT, "каждый привязан к одной странице PDF", False),
        ("Токенов модели", 0, INT, "поиск SQLite FTS5 с русским стеммером и BM25, без эмбеддингов", False),
        ("Стоимость индексации, ₽", 0, RUB, "OCR Tesseract работает на сервере продукта, внешних вызовов нет", False),
        ("Время сборки индекса, с", info.index_seconds, "0", "замер на чистой копии; повторяется только при "
         "добавлении руководств", True),
    ])
    block(12, "Стенд", [
        ("VPS, ₽ в месяц без НДС", info.vps_rub, RUB, "впишите по счёту хостинга: сервер, интерфейс, заглушки ML и "
         "ТОиР, индекс на одной машине, видеокарта не нужна", True),
        ("Модель", "по API", None, "оплата за токены, лист «На 1 запрос»", False),
    ])
    block(17, "Если модель локальная (в контуре заказчика)", [
        ("Цена токенов в листе «На 1 запрос»", 0, RUB, "цены входа и выхода ставятся 0, затраты переходят в сервер "
         "с видеокартой", False),
        ("Свой сервер с GPU, ₽", 0, RUB, "модель 30 млрд параметров в 4 битах: 24–48 ГБ видеопамяти "
         "(docs/local-model.md)", True),
        ("Срок амортизации, месяцев", 36, INT, "линейная амортизация", True),
        ("Мощность сервера, кВт", 0, "0.00", "", True),
        ("Часов работы в месяц", 720, INT, "круглосуточно; по графику смен меньше", True),
        ("Тариф на электричество, ₽ за кВт·ч", 0, RUB, "", True),
        ("Обслуживание, ₽ в месяц", 0, RUB, "", True),
        ("Своё железо, ₽ в месяц", "=B20/B21+B22*B23*B24+B25", RUB, "сервер ÷ срок + электричество + обслуживание",
         False),
        ("Аренда GPU, ₽ за час", 0, RUB, "эквивалент своего железа у облачного провайдера", True),
        ("Часов аренды в месяц", 720, INT, "", True),
        ("Аренда GPU, ₽ в месяц", "=B27*B28", RUB, "ставка × часы", False),
        ("Своё железо на проверку, ₽", f"=IF('{SHEETS[1]}'!B20>0,B26/'{SHEETS[1]}'!B20,0)", RUB,
         "месячная стоимость ÷ проверок в месяц на парк", False),
        ("Аренда на проверку, ₽", f"=IF('{SHEETS[1]}'!B20>0,B29/'{SHEETS[1]}'!B20,0)", RUB, "", False),
    ])
    _note(ws, 34, "Качество локальной модели проверяется тем же набором из 21 вопроса; проверена только Qwen2.5 7B "
                  "(14 из 21), класс 30 млрд параметров не проверялся.", end=3)
    _widths(ws, {"A": 38, "B": 16, "C": 70})
    return {"vps": "B14"}


def _sheet_calls(ws, m: Measurement) -> None:
    titles = ["Время вызова", "Машина", "Механик", "Сценарий", "Ход", "Итог хода", "Шаг агента", "Модель",
              "Токенов на входе", "Токенов на выходе", "Из кэша", "₽ по журналу (цены настроек)", "Время ответа, с"]
    _header(ws, 1, titles)
    for i, c in enumerate(m.calls, start=2):
        row = [c["created_at"], c["vehicle_id"], c["author"] or "", c["scenario_id"], c["turn_id"], c["kind"] or "",
               c["step"], c["model"], c["input_tokens"], c["output_tokens"], c["cache_read_tokens"], c["cost_rub"],
               c["duration_ms"] / 1000]
        for col, value in enumerate(row, start=1):
            cell = ws.cell(row=i, column=col, value=value)
            cell.number_format = {9: INT, 10: INT, 11: INT, 12: RUB, 13: "0.0"}.get(col, "General")
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(titles))}{max(len(m.calls) + 1, 2)}"
    _widths(ws, {"A": 26, "B": 12, "C": 16, "D": 10, "E": 8, "F": 14, "G": 30, "H": 28, "I": 12, "J": 12, "K": 12,
                 "L": 14, "M": 10})


def build(m: Measurement, prices: Prices, info: Info) -> Workbook:
    wb = Workbook()
    ws1 = wb.active
    ws1.title = SHEETS[0]
    ws2, ws3, ws4 = (wb.create_sheet(name) for name in SHEETS[1:])
    refs = _sheet_request(ws1, m, prices, info)
    stand = _sheet_stand(ws3, info)
    _sheet_fleet(ws2, refs, stand)
    _sheet_calls(ws4, m)
    return wb


def _calls(store: Store, f: Filters) -> list[dict]:
    return store.llm_calls(f.date_from, f.date_to, f.model, f.vehicle_id, f.mechanic)


def export(store: Store, settings: Settings, filters: Filters, *, kb: dict | None = None, vat: float | None = None,
           index_seconds: float | None = None, vps_rub: float | None = None, prices: Prices | None = None,
           questions: Filters | None = None) -> bytes:
    """xlsx по журналу. questions: где считать отдельный вопрос механика, если не в том же отборе."""
    prices = prices or Prices.from_settings(settings, vat)
    m = measure(_calls(store, filters), store.stt_calls(filters.date_from, filters.date_to), store.stt_calls(), prices,
                question_calls=_calls(store, questions) if questions else None,
                question_where=f" ({questions.describe()})" if questions else "")
    info = Info(filters=filters, stt_model=settings.stt_model, kb=kb or {}, index_seconds=index_seconds,
                vps_rub=vps_rub, generated=datetime.now().astimezone().isoformat(timespec="minutes"))
    buffer = io.BytesIO()
    build(m, prices, info).save(buffer)
    return buffer.getvalue()


def _kb_stats(path: Path) -> dict:
    """Размер базы знаний без записи в индекс."""
    db = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True)
    try:
        one = lambda sql: db.execute(sql).fetchone()[0]  # noqa: E731
        return {"manuals": one("SELECT COUNT(DISTINCT manual_id) FROM pages"), "pages": one("SELECT COUNT(*) FROM pages"),
                "chunks": one("SELECT COUNT(*) FROM chunks"), "ocr_pages": one("SELECT COUNT(*) FROM pages WHERE ocr=1")}
    finally:
        db.close()


def main() -> None:
    """Файл расчёта по готовой базе журнала (например, архиву стенда): цены и НДС задаются явно.

    База открывается в копии: Store дописывает схему, а архив прогона менять нельзя.
    """
    from .config import get_settings

    parser = argparse.ArgumentParser(description="Расчёт стоимости в xlsx по журналу вызовов модели")
    parser.add_argument("--db", required=True, type=Path, help="app.sqlite с журналом")
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--from", dest="date_from")
    parser.add_argument("--to", dest="date_to")
    parser.add_argument("--model")
    parser.add_argument("--questions-from", help="начало прогона вопросов, если отдельный вопрос считать по нему")
    parser.add_argument("--questions-to")
    parser.add_argument("--prices", help="вход,выход,чтение кэша,запись в кэш за 1 млн, как в прайсе")
    parser.add_argument("--currency", default=None)
    parser.add_argument("--vat", type=float, default=None, help="НДС в ценах, %%")
    parser.add_argument("--stt-price", type=float, default=None, help="₽ за минуту распознавания, как в прайсе")
    parser.add_argument("--source", default="", help="ссылка на прайс для комментария")
    parser.add_argument("--kb", type=Path, help="index.sqlite базы знаний для листа индексации")
    parser.add_argument("--index-seconds", type=float, default=None)
    parser.add_argument("--vps", type=float, default=None, help="VPS, ₽ в месяц без НДС")
    args = parser.parse_args()

    settings = get_settings()
    base = Prices.from_settings(settings)
    inp, out, read, write = (float(x) for x in args.prices.split(",")) if args.prices else (
        base.input, base.output, base.cache_read, base.cache_write)
    currency = (args.currency or base.currency).upper()
    vat = args.vat / 100 if args.vat is not None else (0.05 if currency == "RUB" else 0.0)
    prices = Prices(inp, out, read, write, currency, base.usd_rate,
                    base.stt_per_min if args.stt_price is None else args.stt_price, vat, args.source)
    kb = _kb_stats(args.kb) if args.kb else {}
    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / "app.sqlite"
        shutil.copyfile(args.db, copy)
        store = Store(copy)
        data = export(store, settings, Filters(args.date_from, args.date_to, args.model), kb=kb,
                      index_seconds=args.index_seconds, vps_rub=args.vps, prices=prices,
                      questions=Filters(args.questions_from, args.questions_to, args.model)
                      if args.questions_from or args.questions_to else None)
        store.close()
    args.out.write_bytes(data)
    print(f"{args.out}: {len(data)} байт")


if __name__ == "__main__":
    main()
