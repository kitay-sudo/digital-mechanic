"""Картинка страницы руководства с подсветкой цитаты.

Механик открывает источник и видит, откуда взят норматив. PDF читаются из KB_DIR/pdf
и в репозиторий не входят.
"""
from __future__ import annotations

from functools import lru_cache

import pymupdf

from ..config import get_settings
from ..manuals import manual_by_id
from .text import clean_page_text

TARGET_WIDTH = 1400


def _segments(quote: str) -> list[str]:
    """Цитата может идти в несколько строк: ищем её кусками по несколько слов."""
    words = clean_page_text(quote).split()
    if not words:
        return []
    out = []
    for start in range(0, len(words), 4):
        part = words[start:start + 5]
        if len(" ".join(part)) >= 8:
            out.append(" ".join(part))
    return out or [" ".join(words)]


@lru_cache(maxsize=64)
def page_png(manual_id: str, page: int, quote: str = "") -> bytes | None:
    manual = manual_by_id(manual_id)
    if manual is None:
        return None
    path = get_settings().pdf_dir / manual.file
    if not path.exists():
        return None
    with pymupdf.open(path) as doc:
        if page < 1 or page > len(doc):
            return None
        pdf_page = doc[page - 1]
        if quote:
            # Четырёхугольники, а не прямоугольники: на повёрнутом тексте (таблицы в альбомной ориентации)
            # выделение идёт вдоль строки, а не огромными овалами поперёк страницы
            quads = []
            for segment in _segments(quote):
                quads.extend(pdf_page.search_for(segment, quads=True))
            for quad in quads:
                try:
                    annot = pdf_page.add_highlight_annot(quad)
                    annot.set_colors(stroke=(1.0, 0.82, 0.2))
                    annot.update()
                except Exception:
                    continue
        zoom = TARGET_WIDTH / pdf_page.rect.width
        pix = pdf_page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
        return pix.tobytes("png")
