"""Проверка ответа агента кодом: ссылки, цитаты и числа.

П1: документ ссылки относится к двигателю машины.
П2: цитата дословно стоит на указанной странице PDF.
П3: число в пункте из руководства есть на процитированной странице; число без источника — ошибка.
П4: гипотезы идут отдельным списком и нормативов не содержат.
П18: расхождение между источниками — это не меньше двух разных цитат, каждая сверена со своей страницей.
"""
from __future__ import annotations

import re

from ..kb.index import Index
from ..kb.text import clean_page_text, is_toc, quote_on_page, quote_too_short, squash, strip_service_numbers
from ..manuals import manual_by_id

_NUM = re.compile(r"(?<![0-9a-zа-яё.,])(\d+(?:[.,]\d+)?)(?![0-9a-zа-яё]|[.,]\d)", re.IGNORECASE)
_UNIT = re.compile(
    r"^\s*(?:[-–]\s*\d+(?:[.,]\d+)?\s*)?(мм|см|мкм|м\b|кгс|н[·*.\s]?м|нм\b|мпа|кпа|па\b|бар|атм|кг\b|г\b|л\b|мл|°|град|об|мин|сек|с\b|ч\b|в\b|а\b|ом|%|км|шт)",
    re.IGNORECASE,
)


def _norm(raw: str) -> str:
    value = raw.replace(",", ".")
    if "." in value:
        value = value.rstrip("0").rstrip(".")
    return value or "0"


_ANY_NUM = re.compile(r"\d+(?:[.,]\d+)?")


def page_numbers(text: str) -> set[str]:
    """Все числа страницы, включая стоящие внутри обозначений («6hx145»): со страницей сверяем щедро,
    чтобы не отбрасывать верный пункт из-за формы записи. Строго проверяется текст ответа."""
    return {_norm(m.group(0)) for m in _ANY_NUM.finditer(clean_page_text(text))}


def stray_numbers(text: str, allowed: set[str], strict: bool) -> list[str]:
    """Числа из текста, которых нет среди разрешённых.

    strict=False (пояснения, гипотезы): небольшие целые без единицы измерения не считаются
    нормативом («3 проверки подряд»).
    """
    out = []
    cleaned = strip_service_numbers(text)
    for match in _NUM.finditer(cleaned):
        value = _norm(match.group(1))
        if value in allowed:
            continue
        if not strict and "." not in value and int(value) <= 10 and not _UNIT.match(cleaned[match.end():]):
            continue
        out.append(match.group(1))
    return out


class Verifier:
    def __init__(self, index: Index, allowed_manuals: list[str], context_numbers: set[str]):
        self.index = index
        self.allowed = set(allowed_manuals)
        self.context_numbers = context_numbers
        self._pages: dict[tuple[str, int], str | None] = {}

    def page(self, manual_id: str, page: int) -> str | None:
        key = (manual_id, page)
        if key not in self._pages:
            self._pages[key] = self.index.page_text(manual_id, page)
        return self._pages[key]

    def check_ref(self, ref: dict) -> tuple[dict | None, str | None]:
        manual_id = str(ref.get("manual_id", ""))
        try:
            page = int(ref.get("pdf_page"))
        except (TypeError, ValueError):
            return None, "в ссылке нет номера страницы"
        quote = str(ref.get("quote", "")).strip()
        manual = manual_by_id(manual_id)
        if manual is None:
            return None, f"документа «{manual_id}» нет в базе знаний"
        if manual_id not in self.allowed:
            return None, f"документ {manual.designation} относится к другому двигателю"
        text = self.page(manual_id, page)
        if text is None:
            return None, f"в документе {manual.designation} нет страницы {page}"
        if is_toc(text):
            return None, f"стр. {page} документа {manual.designation} — оглавление, оно источником не считается"
        if quote_too_short(quote):
            return None, (f"цитата «{quote[:60]}» слишком короткая: возьми строку целиком, вместе с названием параметра "
                          f"(стр. {page} документа {manual.designation})")
        if not quote_on_page(quote, text):
            return None, f"цитата «{quote[:90]}» не найдена дословно на стр. {page} документа {manual.designation}"
        return {
            "manual_id": manual_id, "designation": manual.designation, "short": manual.short,
            "pdf_page": page, "quote": quote,
        }, None

    def check_items(self, items: list[dict], label: str) -> tuple[list[dict], list[str]]:
        """Пункты «из руководства»: у каждого должна быть проверенная ссылка, числа — со страницы."""
        good, problems = [], []
        for item in items or []:
            text = str(item.get("text", "")).strip()
            if not text:
                continue
            refs, errors = [], []
            for ref in item.get("refs") or []:
                ok, err = self.check_ref(ref)
                if ok:
                    refs.append(ok)
                elif err:
                    errors.append(err)
            if not refs:
                reason = "; ".join(errors) if errors else "нет ссылки на страницу руководства"
                problems.append(f"{label}: пункт «{text[:80]}» не подтверждён ({reason})")
                continue
            allowed = set(self.context_numbers)
            for ref in refs:
                allowed |= page_numbers(self.page(ref["manual_id"], ref["pdf_page"]) or "")
            stray = stray_numbers(text, allowed, strict=True)
            if stray:
                problems.append(
                    f"{label}: в пункте «{text[:80]}» числа {', '.join(stray)} отсутствуют на процитированных страницах"
                )
                continue
            good.append({"text": text, "refs": refs})
        return good, problems

    def check_free_text(self, items: list[str], label: str, cited_numbers: set[str]) -> tuple[list[str], list[str]]:
        """Пояснения и гипотезы: числа допустимы только из результата проверки или с процитированных страниц."""
        good, problems = [], []
        allowed = self.context_numbers | cited_numbers
        for text in items or []:
            text = str(text).strip()
            if not text:
                continue
            stray = stray_numbers(text, allowed, strict=False)
            if stray:
                problems.append(f"{label}: в тексте «{text[:80]}» числа {', '.join(stray)} без источника")
                continue
            good.append(text)
        return good, problems

    def check_conflicts(self, blocks: list[dict]) -> tuple[list[dict], list[str]]:
        """П18: в расхождении остаются только формулировки, дословно стоящие на своих страницах."""
        good, problems = [], []
        for block in blocks or []:
            topic = str(block.get("topic", "")).strip()
            statements, numbers = [], set(self.context_numbers)
            for statement in block.get("statements") or []:
                ref, err = self.check_ref(statement.get("ref") or {})
                if ref is None:
                    problems.append(f"Расхождение «{topic[:60]}»: формулировка не подтверждена ({err})")
                    continue
                on_page = page_numbers(self.page(ref["manual_id"], ref["pdf_page"]) or "")
                numbers |= on_page
                text = str(statement.get("text", "")).strip()
                if stray_numbers(text, self.context_numbers | on_page, strict=True):
                    text = ""  # пересказ с чужим числом не показываем, остаётся дословная цитата
                statements.append({"text": text, "ref": ref})
            if len({squash(s["ref"]["quote"]) for s in statements}) < 2:
                problems.append(f"Расхождение «{topic[:60]}»: нужны две разные формулировки с цитатами со страниц")
                continue
            if not topic or stray_numbers(topic, numbers, strict=False):
                topic = "Источники расходятся"
            good.append({"topic": topic, "statements": statements})
        return good, problems

    def verify_answer(self, answer: dict) -> tuple[dict, list[str]]:
        problems: list[str] = []
        found, p = self.check_conflicts(answer.get("conflicts"))
        problems += p
        checks, p = self.check_items(answer.get("checks"), "Проверки")
        problems += p
        repair, p = self.check_items(answer.get("repair"), "Ремонт")
        problems += p
        cited: set[str] = set()
        for item in checks + repair:
            for ref in item["refs"]:
                cited |= page_numbers(self.page(ref["manual_id"], ref["pdf_page"]) or "")
        for block in found:
            for statement in block["statements"]:
                cited |= page_numbers(self.page(statement["ref"]["manual_id"], statement["ref"]["pdf_page"]) or "")
        observations, p = self.check_free_text(answer.get("observations"), "Наблюдения", cited)
        problems += p
        hypotheses, p = self.check_free_text(answer.get("hypotheses"), "Гипотезы", cited)
        problems += p
        limitations, p = self.check_free_text(answer.get("limitations"), "Ограничения", cited)
        problems += p
        summary_list, p = self.check_free_text([answer.get("summary", "")], "Вывод", cited)
        problems += p
        clean = {
            "summary": summary_list[0] if summary_list else "",
            "observations": observations,
            "hypotheses": hypotheses,
            "checks": checks,
            "repair": repair,
            "limitations": limitations,
            "conflicts": found,
            "not_found": bool(answer.get("not_found")) and not (checks or repair or found),
        }
        return clean, problems
