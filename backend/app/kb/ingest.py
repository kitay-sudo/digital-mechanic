"""Подготовка базы знаний: PDF → текст по страницам → фрагменты → индекс.

Запуск:  python -m app.kb.ingest
PDF берутся из KB_DIR/pdf, имена файлов заданы в config/manuals.json.
Страницы, где текста почти нет (чертежи и таблицы картинкой), распознаются
Tesseract, если он установлен. Без него такие страницы остаются как есть.
"""
from __future__ import annotations

import shutil
import sys
import time

import pymupdf

from ..config import get_settings
from ..manuals import all_manuals
from .index import get_index
from .text import clean_page_text, is_toc

LOW_TEXT = 200      # меньше символов на странице: пробуем распознавание
CHUNK = 1100        # размер фрагмента в символах
OVERLAP = 220


def chunk_page(text: str) -> list[str]:
    """Режет текст страницы на перекрывающиеся фрагменты по границам строк."""
    text = clean_page_text(text)
    lines = [" ".join(line.split()) for line in text.splitlines()]
    lines = [line for line in lines if line]
    chunks, cur, size = [], [], 0
    for line in lines:
        cur.append(line)
        size += len(line) + 1
        if size >= CHUNK:
            chunks.append("\n".join(cur))
            tail, tail_size = [], 0
            for prev in reversed(cur):
                if tail_size + len(prev) > OVERLAP:
                    break
                tail.insert(0, prev)
                tail_size += len(prev) + 1
            cur, size = tail, tail_size
    if cur and (not chunks or size > OVERLAP + 40):
        chunks.append("\n".join(cur))
    return [c for c in chunks if len(c.strip()) >= 30]


def ocr_page(page: pymupdf.Page) -> str:
    textpage = page.get_textpage_ocr(language="rus+eng", dpi=220, full=True)
    return page.get_text(textpage=textpage)


def main() -> int:
    settings = get_settings()
    index = get_index()
    has_ocr = shutil.which("tesseract") is not None
    if not has_ocr:
        print("Tesseract не найден: страницы без текстового слоя останутся без распознавания.")
    index.reset()
    total_pages = total_chunks = total_ocr = 0
    for manual in all_manuals():
        path = settings.pdf_dir / manual.file
        if not path.exists():
            print(f"НЕТ ФАЙЛА: {path}. Руководство {manual.designation} пропущено.")
            continue
        started = time.time()
        doc = pymupdf.open(path)
        if len(doc) != manual.pages:
            print(f"Внимание: в {manual.file} {len(doc)} страниц, в реестре {manual.pages}.")
        ocr_count = 0
        for number, page in enumerate(doc, start=1):
            text = page.get_text()
            used_ocr = False
            if len(text.strip()) < LOW_TEXT and has_ocr:
                try:
                    recognized = ocr_page(page)
                    if len(recognized.strip()) > len(text.strip()):
                        text, used_ocr = recognized, True
                        ocr_count += 1
                except Exception as exc:  # распознавание не должно ронять сборку индекса
                    print(f"  стр. {number}: распознавание не удалось ({exc})")
            # Оглавление в поиск не попадает: это не процедура и не норматив (П9).
            chunks = [] if is_toc(text) else chunk_page(text)
            index.add_page(manual.id, number, text, used_ocr, chunks)
            total_chunks += len(chunks)
        index.commit()
        total_pages += len(doc)
        total_ocr += ocr_count
        print(f"{manual.designation}: {len(doc)} стр., распознано {ocr_count}, {time.time() - started:.1f} с")
    print(f"Готово: {total_pages} страниц, {total_chunks} фрагментов, распознано страниц: {total_ocr}.")
    print(f"Индекс: {settings.index_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
