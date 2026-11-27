"""Распознавание речи на сервере.

Механик говорит, браузер записывает фразу и присылает звук сюда. Сервер отдаёт его модели распознавания
по протоколу OpenAI (POST /audio/transcriptions). Через ProxyAPI это gpt-4o-mini-transcribe, в закрытом
контуре — свой сервер Whisper с тем же протоколом (например, faster-whisper): меняется только STT_BASE_URL.
Без STT_BASE_URL распознаёт сам браузер, как раньше.

Распознавание в браузере работает не везде (нет в Firefox и во встроенном WebView Android) и не даёт
показать механику, что его слышно. Запись на сервер работает в любом браузере с микрофоном.
"""
from __future__ import annotations

import re

import httpx

from .config import Settings

# Подсказка модели распознавания: названия и термины, которые без неё пишутся с ошибками.
GLOSSARY = (
    "Механик автопарка спрашивает про двигатель. Термины: ЯМЗ-236М2, ЯМЗ-536, ЗМЗ-5234, ЗМЗ-409, ТНВД, форсунка, "
    "ГРМ, коленвал, распредвал, клапан, тепловой зазор, момент затяжки, кгс·м, Н·м, коренные подшипники, шатун, "
    "турбокомпрессор, гидронатяжитель, дефектовка, заявка, ТОиР, госномер."
)
# Что модели распознавания «слышат» в тишине и шуме: такую фразу механику не отправляем.
_PHANTOM = re.compile(r"субтитр|dimatorzok|продолжение следует|спасибо за (просмотр|внимание)|редактор субтитров", re.I)
_EXT = {"webm": "webm", "ogg": "ogg", "mp4": "mp4", "m4a": "m4a", "aac": "m4a", "mpeg": "mp3", "mp3": "mp3",
        "wav": "wav", "x-wav": "wav"}


class STTError(Exception):
    """Ошибка распознавания с текстом для механика."""


def _extension(content_type: str) -> str:
    subtype = content_type.split(";")[0].strip().lower().split("/")[-1]
    return _EXT.get(subtype, "webm")


def clean(text: str) -> str:
    text = " ".join((text or "").split())
    if _PHANTOM.search(text) and len(text) < 80:
        return ""
    return text


async def transcribe(audio: bytes, content_type: str, settings: Settings) -> str:
    url = settings.stt_base_url.rstrip("/") + "/audio/transcriptions"
    headers = {"Authorization": f"Bearer {settings.stt_api_key}"} if settings.stt_api_key else {}
    files = {"file": (f"speech.{_extension(content_type)}", audio, content_type.split(";")[0] or "audio/webm")}
    data = {"model": settings.stt_model, "language": "ru", "prompt": GLOSSARY, "response_format": "json"}
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(url, headers=headers, data=data, files=files)
    except httpx.HTTPError as exc:
        raise STTError("Нет связи с сервисом распознавания речи. Повторите или введите текст.") from exc
    if response.status_code in (401, 403):
        raise STTError("Ключ сервиса распознавания речи не принят. Проверьте STT_API_KEY.")
    if response.status_code >= 400:
        raise STTError(f"Сервис распознавания речи не принял запись (код {response.status_code}). Повторите.")
    try:
        return clean(response.json().get("text", ""))
    except ValueError as exc:
        raise STTError("Сервис распознавания речи вернул непонятный ответ. Повторите.") from exc
