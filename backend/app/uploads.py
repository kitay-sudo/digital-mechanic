"""Фото узла от механика (на кик-оффе заказчик назвал вход «текст, голос и картинки»).

Интерфейс уменьшает снимок до 1568 px по длинной стороне и присылает его в сообщении чата как data URL.
Сервер проверяет, что это действительно картинка, сохраняет её в DATA_DIR/uploads и отдаёт модели
вместе с вопросом. В переписке остаётся ссылка на файл, сам снимок в базу не пишется.
"""
from __future__ import annotations

import base64
import binascii
import re
import uuid
from pathlib import Path

MAX_PHOTOS = 3
MAX_BYTES = 6 * 1024 * 1024
_DATA_URL = re.compile(r"^data:(image/(?:jpeg|png|webp));base64,([A-Za-z0-9+/=\s]+)$")
_NAME = re.compile(r"^[0-9a-f]{32}\.(jpg|png|webp)$")
_EXT = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}
_MEDIA = {v: k for k, v in _EXT.items()}
_MAGIC = {"image/jpeg": (b"\xff\xd8\xff",), "image/png": (b"\x89PNG\r\n\x1a\n",), "image/webp": (b"RIFF",)}


class PhotoError(ValueError):
    """Снимок не принят: текст для механика."""


def folder(data_dir: Path) -> Path:
    return data_dir / "uploads"


def save(data_urls: list[str], data_dir: Path) -> list[dict]:
    """Проверяет и сохраняет снимки. Возвращает записи для сообщения чата: id и адрес."""
    if len(data_urls) > MAX_PHOTOS:
        raise PhotoError(f"К одному сообщению можно приложить не больше {MAX_PHOTOS} фото.")
    out = []
    target = folder(data_dir)
    for data_url in data_urls:
        match = _DATA_URL.match(data_url or "")
        if not match:
            raise PhotoError("Фото не распознано: нужен снимок JPEG, PNG или WebP.")
        media_type = match.group(1)
        try:
            raw = base64.b64decode(match.group(2), validate=False)
        except (binascii.Error, ValueError) as exc:
            raise PhotoError("Фото повреждено при отправке. Сфотографируйте ещё раз.") from exc
        if len(raw) > MAX_BYTES:
            raise PhotoError("Фото слишком большое. Сфотографируйте ещё раз.")
        if not raw.startswith(_MAGIC[media_type]) or (media_type == "image/webp" and raw[8:12] != b"WEBP"):
            raise PhotoError("Файл не похож на фото. Приложите снимок JPEG, PNG или WebP.")
        name = f"{uuid.uuid4().hex}.{_EXT[media_type]}"
        target.mkdir(parents=True, exist_ok=True)
        (target / name).write_bytes(raw)
        out.append({"id": name, "url": f"/api/uploads/{name}"})
    return out


def path_of(name: str, data_dir: Path) -> Path | None:
    if not _NAME.match(name):
        return None
    path = folder(data_dir) / name
    return path if path.is_file() else None


def media_type(name: str) -> str:
    return _MEDIA[name.rsplit(".", 1)[-1]]


def image_block(name: str, data_dir: Path) -> dict | None:
    """Блок изображения во внутреннем формате сообщений (как в Messages API)."""
    path = path_of(name, data_dir)
    if path is None:
        return None
    return {"type": "image", "source": {"type": "base64", "media_type": media_type(name),
                                        "data": base64.b64encode(path.read_bytes()).decode("ascii")}}
