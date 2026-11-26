"""Работа с текстом руководств: нормализация, основы слов, сверка цитат и чисел."""
from __future__ import annotations

import re
from functools import lru_cache

import snowballstemmer

_stemmer = snowballstemmer.stemmer("russian")

STOPWORDS = frozenset(
    """и в во не что он на я с со как а то все она так его но да ты к у же вы за бы по только ее мне
    было вот от меня еще нет о из ему теперь когда даже ну вдруг ли если уже или ни быть был него до
    вас нибудь опять уж вам ведь там потом себя ничего ей может они тут где есть надо ней для мы тебя
    их чем была сам чтоб без будто чего раз тоже себе под будет ж тогда кто этот того потому этого
    какой какая какое какие совсем ним здесь этом один почти мой тем чтобы нее сейчас были куда зачем
    всех никогда можно при наконец два об другой хоть после над больше тот через эти нас про всего
    них какая много разве три эту моя впрочем хорошо свою этой перед иногда лучше чуть том нельзя
    такой им более всегда конечно всю между это нужно нужен нужна должен должна должно какой-то""".split()
)

_WORD = re.compile(r"[0-9a-zа-яё]+(?:[.,][0-9]+)*", re.IGNORECASE)
_NUMBER = re.compile(r"(?<![0-9a-zа-яё.,])\d+(?:[.,]\d+)?(?![0-9a-zа-яё]|[.,]\d)", re.IGNORECASE)


def clean_page_text(text: str) -> str:
    """Убирает переносы слов и мягкие дефисы, чтобы слово искалось целиком."""
    text = text.replace("­", "").replace(" ", " ")
    text = re.sub(r"(?<=[а-яёa-z])-\s*\n\s*(?=[а-яёa-z])", "", text)
    return text


@lru_cache(maxsize=50_000)
def stem(word: str) -> str:
    return _stemmer.stemWord(word)


def tokens(text: str) -> list[str]:
    """Слова в нижнем регистре: русские приведены к основе, числа и обозначения как есть."""
    out: list[str] = []
    for raw in _WORD.findall(text.lower().replace("ё", "е")):
        if raw in STOPWORDS:
            continue
        if raw[0].isdigit() or not re.search(r"[а-я]", raw):
            out.append(raw.replace(",", "."))
        else:
            out.append(stem(raw))
    return out


def stem_text(text: str) -> str:
    return " ".join(tokens(text))


def squash(text: str) -> str:
    """Только буквы и цифры: сравнение цитаты со страницей не зависит от пробелов и знаков."""
    text = clean_page_text(text).lower().replace("ё", "е")
    return re.sub(r"[^0-9a-zа-я]+", "", text)


def quote_on_page(quote: str, page_text: str, min_len: int = 16) -> bool:
    """Правило П2: цитата должна дословно стоять на странице."""
    q = squash(quote)
    if len(q) < min_len:
        return False
    return q in squash(page_text)


def numbers(text: str) -> set[str]:
    """Числа из текста в едином виде: запятая заменена точкой, нули в хвосте убраны."""
    found = set()
    for raw in _NUMBER.findall(text):
        value = raw.replace(",", ".")
        if "." in value:
            value = value.rstrip("0").rstrip(".")
        found.add(value or "0")
    return found


_IGNORED = re.compile(
    r"\bF\d{2}\b|\bS-\d+\b|\bTKT-\d+\b|\b\d{1,2}\.\d{1,2}(?:\.\d{2,4})?\b(?=\s|$|[),;])|стр\.?\s*\d+|с\.\s*\d+",
    re.IGNORECASE,
)


def strip_service_numbers(text: str) -> str:
    """Убирает то, что числом-нормативом не является: коды, номера проверок, страницы."""
    return _IGNORED.sub(" ", text)


_TOC_LINE = re.compile(r"(?:\.\s*){6,}\s*\d{1,3}\s*$")


def is_toc(page_text: str) -> bool:
    """Страница оглавления: много строк с отточием и номером страницы. Доказательством не считается (П9)."""
    lines = [line for line in page_text.splitlines() if line.strip()]
    hits = sum(1 for line in lines if _TOC_LINE.search(line))
    return hits >= 5 or (len(lines) > 0 and page_text.count(". . . .") + page_text.count(".....") >= 8)


_INJECTION = re.compile(
    r"\bsystem\b|\bassistant\b|ассистент|ai[\s-]?агент|\bагент|инструкци|промпт|\bprompt\b|\bignore\b|игнорир",
    re.IGNORECASE,
)


def sanitize_description(text: str) -> tuple[str, bool]:
    """Описание признаков от ML-сервиса — данные, а не команды (П17).

    Если в описании есть обращение к агенту или «инструкции», такая фраза и всё после неё
    отбрасываются. Возвращает очищенный текст и признак, что посторонний текст был.
    """
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    kept = []
    for sentence in sentences:
        if _INJECTION.search(sentence):
            return " ".join(kept).strip() or "Описание признаков отсутствует", True
        kept.append(sentence)
    return " ".join(kept).strip(), False


def split_sentences(text: str) -> list[str]:
    text = clean_page_text(text)
    text = re.sub(r"[ \t]+", " ", text)
    parts = re.split(r"(?<=[.;!?])\s+(?=[А-ЯЁA-Z0-9])|\n{2,}", text)
    out = []
    for part in parts:
        s = " ".join(part.split())
        if s:
            out.append(s)
    return out
