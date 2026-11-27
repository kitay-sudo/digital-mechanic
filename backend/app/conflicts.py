"""Противоречия между документами (правило П18, ответ заказчика в чате 26.11.2026).

Если две инструкции по одному вопросу расходятся, агент не выбирает одну как бесспорную:
показывает обе формулировки с документом и страницей, отмечает расхождение, советует до уточнения
у производителя работать по более осторожной формулировке. К «специалисту» механика не отсылаем:
по ответу заказчика на Q&A 27.11 специалист он сам, допустим только контакт производителя.

Расхождения приходят из двух мест:
1. Модель находит их сама при чтении страниц и отдаёт в поле conflicts. Код сверяет цитаты.
2. Реестр подтверждённых расхождений (config/conflicts.json). Он срабатывает без модели:
   если вопрос или шаги ответа касаются темы из реестра, блок расхождения добавляет код.

В реестре нет текста руководств: только документ, страница и слова-маркеры. Саму формулировку
код берёт со страницы PDF во время работы.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache

from .config import get_settings
from .kb.index import Index
from .kb.text import split_sentences, squash
from .manuals import manual_by_id

RECOMMENDATION = (
    "Не принимайте одну из формулировок как бесспорную. До ответа производителя работайте по более "
    "осторожной из них и уточните у производителя для вашей модификации двигателя."
)
MAX_QUOTE = 360
_WORD = re.compile(r"[a-zа-я0-9]+")
_SECTION = re.compile(r"\d+(?:\.\d+)+\s+(?=[А-ЯЁ])")  # номер пункта перед фразой: «6.4.1 Проверить…»


@dataclass(frozen=True)
class Known:
    id: str
    topic: str
    keywords: tuple[tuple[str, ...], ...]  # группы начал слов: тема задета, если в тексте есть вся группа
    statements: tuple[dict, ...]
    resolution: str
    resolution_source: str

    def pages(self) -> set[tuple[str, int]]:
        return {(s["manual_id"], int(s["pdf_page"])) for s in self.statements}


@lru_cache
def known_conflicts() -> tuple[Known, ...]:
    path = get_settings().conflicts_config
    if not path.exists():
        return ()
    raw = json.loads(path.read_text(encoding="utf-8"))
    return tuple(
        Known(
            id=item["id"], topic=item["topic"],
            keywords=tuple(tuple(_plain(w) for w in group) for group in item["keywords"]),
            statements=tuple(item["statements"]),
            resolution=item.get("resolution", ""), resolution_source=item.get("resolution_source", ""),
        )
        for item in raw
    )


def _plain(text: str) -> str:
    return text.lower().replace("ё", "е")


def _about(known: Known, text: str) -> bool:
    # Сравнение по началу слова, а не по основе: стеммер режет формы одного слова по-разному.
    words = set(_WORD.findall(_plain(text)))
    return any(all(any(w.startswith(start) for w in words) for start in group) for group in known.keywords)


def _has_markers(text: str, markers: list[str]) -> bool:
    flat = squash(text)
    return all(squash(m) in flat for m in markers)


def _sentence(page_text: str, markers: list[str]) -> str | None:
    """Предложение страницы, где стоят все маркеры: это и есть спорная формулировка."""
    for sentence in split_sentences(page_text):
        if not _has_markers(sentence, markers):
            continue
        # Заголовок раздела, прилипший к фразе, в цитату не берём.
        for match in reversed(list(_SECTION.finditer(sentence))):
            if _has_markers(sentence[match.end():], markers):
                sentence = sentence[match.end():]
                break
        if len(sentence) <= MAX_QUOTE:
            return sentence
    return None


def resolve(known: Known, index: Index, allowed_manuals: list[str]) -> dict | None:
    """Собирает блок расхождения из реестра. Формулировки берутся со страниц дословно."""
    statements = []
    for item in known.statements:
        manual = manual_by_id(item["manual_id"])
        if manual is None or manual.id not in allowed_manuals:
            return None  # расхождение относится к другому двигателю
        page = int(item["pdf_page"])
        text = index.page_text(manual.id, page)
        quote = _sentence(text, item["markers"]) if text else None
        if quote is None:
            continue
        statements.append({"text": "", "ref": {
            "manual_id": manual.id, "designation": manual.designation, "short": manual.short,
            "pdf_page": page, "quote": quote,
        }})
    if len(statements) < 2:
        return None
    return {
        "topic": known.topic, "statements": statements, "recommendation": RECOMMENDATION,
        "confirmed": True, "resolution": known.resolution, "resolution_source": known.resolution_source,
    }


def _item_text(item: dict) -> str:
    return " ".join([item.get("text", ""), *(ref.get("quote", "") for ref in item.get("refs", []))])


def _overlap(a: str, b: str) -> bool:
    a, b = squash(a), squash(b)
    return len(a) >= 16 and len(b) >= 16 and (a in b or b in a)


def from_registry(index: Index, allowed_manuals: list[str], question: str, items: list[dict]) -> list[dict]:
    """Подтверждённые расхождения, которых касается вопрос механика или шаги ответа."""
    out = []
    for known in known_conflicts():
        touched = _about(known, question) or any(
            _about(known, _item_text(item)) and any(
                _has_markers(_item_text(item), s["markers"]) for s in known.statements
            )
            for item in items
        )
        if not touched:
            continue
        block = resolve(known, index, allowed_manuals)
        if block:
            out.append(block)
    return out


def merge(found: list[dict], registry: list[dict]) -> list[dict]:
    """Расхождения от модели и из реестра без повторов: подтверждённое заменяет найденное по тем же страницам."""
    out = list(registry)
    taken = {(s["ref"]["manual_id"], s["ref"]["pdf_page"]) for block in registry for s in block["statements"]}
    for block in found:
        pages = {(s["ref"]["manual_id"], s["ref"]["pdf_page"]) for s in block["statements"]}
        if pages & taken:
            continue
        out.append({**block, "recommendation": RECOMMENDATION, "confirmed": False,
                    "resolution": "", "resolution_source": ""})
    return out


def mark_disputed(items: list[dict], blocks: list[dict]) -> None:
    """Помечает шаг, который повторяет одну из спорных формулировок: его нельзя читать как бесспорный."""
    quotes = [s["ref"] for block in blocks for s in block["statements"]]
    for item in items:
        for ref in item.get("refs", []):
            if any(q["manual_id"] == ref["manual_id"] and q["pdf_page"] == ref["pdf_page"]
                   and (_overlap(q["quote"], ref["quote"]) or _overlap(q["quote"], item.get("text", "")))
                   for q in quotes):
                item["disputed"] = True
                break


def warning_line(block: dict) -> str:
    places = ", ".join(f"{s['ref']['short']} стр. {s['ref']['pdf_page']}" for s in block["statements"])
    return f"В руководствах расхождение: {block['topic'].lower()} ({places}). До начала работы выберите более осторожный вариант и уточните у производителя."
