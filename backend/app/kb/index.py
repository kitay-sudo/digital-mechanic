"""Поисковый индекс по руководствам: SQLite FTS5 по основам слов, ранжирование BM25.

Индекс лежит вне Git рядом с PDF (KB_DIR) и строится командой `python -m app.kb.ingest`.
Каждый фрагмент принадлежит одной странице PDF, поэтому ссылка всегда указывает
на конкретную страницу.
"""
from __future__ import annotations

import sqlite3
import threading
from functools import lru_cache

from ..config import get_settings
from .text import tokens

SCHEMA = """
CREATE TABLE IF NOT EXISTS pages (
    manual_id TEXT NOT NULL, page INTEGER NOT NULL, text TEXT NOT NULL, ocr INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (manual_id, page)
);
CREATE TABLE IF NOT EXISTS chunks (
    id INTEGER PRIMARY KEY, manual_id TEXT NOT NULL, page INTEGER NOT NULL, text TEXT NOT NULL
);
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(stems, tokenize='unicode61 remove_diacritics 0');
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


class Index:
    def __init__(self, path):
        self.path = path
        self._lock = threading.Lock()
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._db.executescript(SCHEMA)

    def stats(self) -> dict:
        with self._lock:
            pages = self._db.execute("SELECT COUNT(*) FROM pages").fetchone()[0]
            chunks = self._db.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
            manuals = self._db.execute("SELECT COUNT(DISTINCT manual_id) FROM pages").fetchone()[0]
            ocr = self._db.execute("SELECT COUNT(*) FROM pages WHERE ocr=1").fetchone()[0]
        return {"manuals": manuals, "pages": pages, "chunks": chunks, "ocr_pages": ocr}

    def page_text(self, manual_id: str, page: int) -> str | None:
        with self._lock:
            row = self._db.execute("SELECT text FROM pages WHERE manual_id=? AND page=?", (manual_id, page)).fetchone()
        return row[0] if row else None

    def page_count(self, manual_id: str) -> int:
        with self._lock:
            return self._db.execute("SELECT COALESCE(MAX(page),0) FROM pages WHERE manual_id=?", (manual_id,)).fetchone()[0]

    def search(self, query: str, manual_ids: list[str], limit: int = 6) -> list[dict]:
        """Лучшие фрагменты по запросу, только из перечисленных руководств (правило П1)."""
        terms = list(dict.fromkeys(tokens(query)))
        if not terms or not manual_ids:
            return []
        match = " OR ".join('"' + t.replace('"', "") + '"' for t in terms[:24])
        marks = ",".join("?" * len(manual_ids))
        sql = (
            "SELECT c.id, c.manual_id, c.page, c.text, bm25(chunks_fts) AS rank, chunks_fts.stems "
            "FROM chunks_fts JOIN chunks c ON c.id = chunks_fts.rowid "
            f"WHERE chunks_fts MATCH ? AND c.manual_id IN ({marks}) ORDER BY rank LIMIT 60"
        )
        with self._lock:
            try:
                rows = self._db.execute(sql, (match, *manual_ids)).fetchall()
            except sqlite3.OperationalError:
                return []
        scored = []
        for _id, manual_id, page, text, rank, stems in rows:
            have = set(stems.split())
            coverage = sum(t in have for t in terms) / len(terms)
            # bm25 в SQLite отрицательный: чем меньше, тем лучше. Добавляем долю покрытых слов запроса.
            scored.append((-rank * (0.4 + coverage), coverage, manual_id, page, text))
        scored.sort(key=lambda r: r[0], reverse=True)
        out, seen = [], set()
        for score, coverage, manual_id, page, text in scored:
            if (manual_id, page) in seen:
                continue
            seen.add((manual_id, page))
            out.append({"manual_id": manual_id, "pdf_page": page, "text": text,
                        "score": round(score, 3), "coverage": round(coverage, 2)})
            if len(out) >= limit:
                break
        return out

    # --- построение ---
    def reset(self) -> None:
        with self._lock:
            self._db.executescript("DELETE FROM pages; DELETE FROM chunks; DELETE FROM chunks_fts; DELETE FROM meta;")
            self._db.commit()

    def add_page(self, manual_id: str, page: int, text: str, ocr: bool, chunks: list[str]) -> None:
        from .text import stem_text

        with self._lock:
            self._db.execute("INSERT OR REPLACE INTO pages VALUES (?,?,?,?)", (manual_id, page, text, int(ocr)))
            for chunk in chunks:
                cur = self._db.execute("INSERT INTO chunks (manual_id, page, text) VALUES (?,?,?)", (manual_id, page, chunk))
                self._db.execute("INSERT INTO chunks_fts (rowid, stems) VALUES (?,?)", (cur.lastrowid, stem_text(chunk)))

    def commit(self) -> None:
        with self._lock:
            self._db.commit()


@lru_cache
def get_index() -> Index:
    settings = get_settings()
    settings.kb_dir.mkdir(parents=True, exist_ok=True)
    return Index(settings.index_path)
