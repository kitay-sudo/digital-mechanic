"""Загрузка материалов задачи при развёртывании: PDF руководств и данные заглушек.

Материалы заказчика в Git не входят (просьба организаторов от 27.11): PDF — документы производителей,
данные заглушек — ответы диагностики и карточки машин. На стенде они скачиваются по ссылке из
переменной MATERIALS_URL, сама ссылка в коде не хранится.

MATERIALS_URL — одна или несколько ссылок через пробел или запятую: прямая ссылка на файл, публичная
ссылка Яндекс Диска, ссылка на файл Google Drive или путь к локальному файлу или папке. Архивы ZIP
распаковываются, вложенные тоже. PDF узнаются по имени из config/manuals.json, а если имя другое — по
числу страниц. vehicles.json и fault_types.json кладутся туда, где их ждут сервер и заглушки.

Запуск из папки backend:  uv run python -m app.materials
В Docker:  docker compose run --rm --no-deps backend uv run --no-dev python -m app.materials
После загрузки собирается индекс базы знаний (флаг --no-index — только скачать и разложить).
"""
from __future__ import annotations

import os
import re
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path
from urllib.parse import quote, urlparse

import httpx
import pymupdf

from .config import get_settings
from .manuals import Manual, all_manuals

DATA_FILES = ("vehicles.json", "fault_types.json")
YANDEX_HOSTS = ("disk.yandex.ru", "disk.yandex.com", "disk.360.yandex.ru", "yadi.sk")


def _direct_url(url: str) -> str:
    """Ссылку облачного диска превращает в ссылку на скачивание файла."""
    host = urlparse(url).netloc.lower()
    if host in YANDEX_HOSTS:
        api = "https://cloud-api.yandex.net/v1/disk/public/resources/download?public_key=" + quote(url, safe="")
        response = httpx.get(api, timeout=60)
        response.raise_for_status()
        return response.json()["href"]
    if host == "drive.google.com":
        found = re.search(r"/file/d/([^/]+)", url) or re.search(r"[?&]id=([^&]+)", url)
        if not found:
            raise ValueError("Ссылка Google Drive на папку не скачивается целиком: дайте ссылку на ZIP-файл.")
        return f"https://drive.usercontent.google.com/download?id={found.group(1)}&export=download&confirm=t"
    return url


def _download(url: str, folder: Path) -> Path:
    target = folder / (Path(urlparse(url).path).name or "download")
    with httpx.stream("GET", _direct_url(url), follow_redirects=True, timeout=httpx.Timeout(60, read=600)) as r:
        r.raise_for_status()
        name = re.search(r"filename\*?=(?:UTF-8'')?\"?([^\";]+)", r.headers.get("content-disposition", ""))
        if name:
            target = folder / Path(name.group(1)).name
        with target.open("wb") as f:
            for block in r.iter_bytes(1 << 20):
                f.write(block)
    print(f"Скачано: {target.name}, {target.stat().st_size / 1e6:.1f} МБ")
    return target


def _zip_name(info: zipfile.ZipInfo) -> str:
    """Имена в архивах из Windows без флага UTF-8 записаны в cp866."""
    if info.flag_bits & 0x800:
        return info.filename
    try:
        return info.filename.encode("cp437").decode("cp866")
    except UnicodeError:
        return info.filename


def _unpack(path: Path) -> None:
    """Распаковывает архив рядом с ним, вложенные архивы тоже. Пути за пределы папки не пропускает."""
    folder = path.with_name(path.name + ".files")
    with zipfile.ZipFile(path) as archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            target = (folder / _zip_name(info)).resolve()
            if not target.is_relative_to(folder.resolve()):
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as src, target.open("wb") as dst:
                shutil.copyfileobj(src, dst)
            if zipfile.is_zipfile(target):
                _unpack(target)


def _gather(source: str, work: Path) -> None:
    local = Path(source)
    if local.is_dir():
        shutil.copytree(local, work / local.name, dirs_exist_ok=True)
        for nested in list((work / local.name).rglob("*.zip")):
            _unpack(nested)
        return
    if local.is_file():
        path = work / local.name
        shutil.copy2(local, path)
    else:
        path = _download(source, work)
    if zipfile.is_zipfile(path):
        _unpack(path)


def _match(pdf: Path, manuals: tuple[Manual, ...]) -> Manual | None:
    by_name = next((m for m in manuals if m.file.lower() == pdf.name.lower()), None)
    if by_name:
        return by_name
    try:
        with pymupdf.open(pdf) as doc:
            pages = len(doc)
    except Exception:
        return None
    same = [m for m in manuals if m.pages == pages]
    return same[0] if len(same) == 1 else None


def place(work: Path) -> list[str]:
    """Раскладывает найденное по местам. Возвращает список того, чего не нашлось."""
    settings = get_settings()
    manuals = all_manuals()
    settings.pdf_dir.mkdir(parents=True, exist_ok=True)
    placed: set[str] = set()
    for pdf in sorted(p for p in work.rglob("*") if p.suffix.lower() == ".pdf"):
        manual = _match(pdf, manuals)
        if manual is None:
            print(f"Пропущен {pdf.name}: не узнан ни по имени, ни по числу страниц")
            continue
        if manual.id not in placed:
            shutil.copy2(pdf, settings.pdf_dir / manual.file)
            placed.add(manual.id)
            print(f"Руководство {manual.designation}: {pdf.name} → {manual.file}")
    targets = {"vehicles.json": settings.fleet_path, "fault_types.json": settings.fault_types_path}
    found: set[str] = set()
    # Файлы из папки data идут первыми: так лежат данные в архиве заглушек.
    for path in sorted(work.rglob("*.json"), key=lambda p: (p.parent.name != "data", len(p.parts))):
        if path.name in targets and path.name not in found:
            targets[path.name].parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, targets[path.name])
            found.add(path.name)
            print(f"Данные заглушек: {path.name} → {targets[path.name]}")
    missing = [f"руководство {m.designation} ({m.file})" for m in manuals if m.id not in placed]
    missing += [f"данные заглушек {name}" for name in DATA_FILES if name not in found]
    return missing


def main(argv: list[str]) -> int:
    sources = [s for s in re.split(r"[\s,]+", os.environ.get("MATERIALS_URL", "")) if s]
    if not sources:
        print("Задайте MATERIALS_URL в .env: ссылку на материалы задачи (см. README).")
        return 2
    with tempfile.TemporaryDirectory(prefix="materials-") as tmp:
        work = Path(tmp)
        for source in sources:
            _gather(source, work)
        missing = place(work)
    if missing:
        print("Не найдено: " + "; ".join(missing))
    if "--no-index" in argv:
        return 1 if missing else 0
    from .kb import ingest

    ingest.main()
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
