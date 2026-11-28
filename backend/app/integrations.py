"""Настройки подключений: адреса ML-сервиса и ТОиР, веб-хук администратора, токены доступа.

Администратор задаёт их в интерфейсе или через /api/v1/settings/integrations. Значения хранятся
в базе и перекрывают .env (config._with_overrides). Пустое значение возвращает настройку из .env.
Секреты (токены, путь веб-хука, пароль в адресе) в ответе маскируются.
"""
from __future__ import annotations

import os
from urllib.parse import urlsplit, urlunsplit

from collections.abc import Callable

from .config import MODEL_KEYS, MODEL_MODES, OVERRIDABLE, OVERRIDE_PREFIX, YANDEX_DEFAULT_MODEL, get_settings
from .db import get_db

# Кто пересоздаёт клиент модели после смены выбора (main.py): новая модель отвечает со следующего вопроса
on_model_change: list[Callable[[], None]] = []

URL_FIELDS = ("ml_url", "toir_url", "alert_webhook_url")
SECRET_FIELDS = ("ml_token", "toir_token")
LABELS = {
    "ml_url": "Адрес ML-сервиса «НейроДВС»",
    "toir_url": "Адрес системы ТОиР",
    "alert_webhook_url": "Веб-хук администратора",
    "ml_token": "Токен ML-сервиса",
    "toir_token": "Токен ТОиР",
    "llm_mode": "Модель",
    "llm_local_url": "Адрес локальной модели",
    "llm_local_model": "Имя локальной модели",
    "llm_local_key": "Ключ локальной модели",
    "yandex_folder": "Каталог Yandex Cloud",
    "yandex_key": "API-ключ Yandex AI Studio",
    "yandex_model": "Модель Yandex AI Studio",
}
MODEL_SECRETS = ("llm_local_key", "yandex_key")
MASK = "•••"


def mask_secret(value: str) -> str | None:
    if not value:
        return None
    return MASK + value[-4:] if len(value) > 8 else MASK


def mask_url(value: str, hide_path: bool = False) -> str:
    """Пароль в адресе и значения параметров скрываются. У веб-хука скрыт и путь: в нём обычно ключ."""
    if not value:
        return ""
    parts = urlsplit(value)
    netloc = parts.netloc
    if "@" in netloc:
        userinfo, host = netloc.rsplit("@", 1)
        user = userinfo.split(":", 1)[0]
        netloc = f"{user}:{MASK}@{host}" if ":" in userinfo else f"{MASK}@{host}"
    path = parts.path
    if hide_path and path.strip("/"):
        path = "/" + MASK
    query = "&".join(f"{p.split('=', 1)[0]}={MASK}" if "=" in p else p for p in parts.query.split("&")) if parts.query else ""
    return urlunsplit((parts.scheme, netloc, path, query, ""))


def is_masked(value: str) -> bool:
    """Интерфейс вернул показанное значение без правки: такое не сохраняется."""
    return MASK in value


def current() -> dict:
    """Действующие настройки для показа: значение (секреты скрыты) и откуда оно — из базы или из .env."""
    settings = get_settings()
    stored = get_db().values(OVERRIDE_PREFIX)
    out: dict = {"items": []}
    for key in OVERRIDABLE:
        value = getattr(settings, key)
        if key in SECRET_FIELDS:
            shown = mask_secret(value)
        else:
            shown = mask_url(value, hide_path=key == "alert_webhook_url")
        out[key] = shown
        out["items"].append({"key": key, "label": LABELS[key], "value": shown, "set": bool(value),
                             "secret": key in SECRET_FIELDS or key == "alert_webhook_url",
                             "source": "db" if key in stored else "env"})
    out["ticket_sink"] = settings.ticket_sink
    out["model"] = model_info(stored)
    return out


def model_info(stored: dict[str, str] | None = None) -> dict:
    """Выбор модели для экрана «Подключения»: вариант, его поля (ключи скрыты) и что отвечает сейчас."""
    settings = get_settings()
    stored = get_db().values(OVERRIDE_PREFIX) if stored is None else stored
    env_cloud = os.environ.get("LLM_PROVIDER", "").strip().lower() in ("", "anthropic") and bool(os.environ.get("ANTHROPIC_API_KEY"))
    return {
        "mode": settings.llm_mode,
        "provider": settings.llm_provider,
        "model": settings.llm_model,
        # Облако из настроек сервера: Claude по встроенному ключу (через ProxyAPI, если задан его адрес)
        "cloud": {"provider": "Claude" if env_cloud else os.environ.get("LLM_PROVIDER", "") or "заглушка",
                  "via_proxyapi": "proxyapi" in os.environ.get("ANTHROPIC_BASE_URL", "").lower(),
                  "model": os.environ.get("LLM_MODEL", ""), "key_builtin": env_cloud},
        "local": {"url": stored.get("llm_local_url", ""),
                  "model": stored.get("llm_local_model", ""),
                  "key": mask_secret(stored.get("llm_local_key", ""))},
        "yandex": {"folder": stored.get("yandex_folder", ""),
                   "key": mask_secret(stored.get("yandex_key", "")),
                   "model": stored.get("yandex_model", "") or YANDEX_DEFAULT_MODEL},
    }


class SettingsError(ValueError):
    def __init__(self, field: str, message: str):
        super().__init__(message)
        self.field = field


def validate_url(field: str, value: str) -> str:
    value = value.strip()
    parts = urlsplit(value)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise SettingsError(field, f"{LABELS[field]}: нужен адрес вида http://сервер:порт или https://сервер")
    return value.rstrip("/")


def update(patch: dict[str, str | None]) -> list[str]:
    """Сохраняет переданные поля. None или скрытое значение — без изменений, пустая строка — вернуть .env.
    Возвращает изменённые поля."""
    db = get_db()
    changed: list[str] = []
    clean: dict[str, str | None] = {}
    for key in OVERRIDABLE:
        if key not in patch or patch[key] is None:
            continue
        value = str(patch[key]).strip()
        if value and is_masked(value):
            continue
        if value and key in URL_FIELDS:
            value = validate_url(key, value)
        if value and key in SECRET_FIELDS and len(value) > 500:
            raise SettingsError(key, f"{LABELS[key]}: слишком длинный")
        clean[key] = value or None
    model = _model_clean(patch, db.values(OVERRIDE_PREFIX))
    for key, value in {**clean, **model}.items():
        db.set_value(OVERRIDE_PREFIX + key, value)
        changed.append(key)
    if changed:
        # Клиенты, правила и оповещения читают адреса из get_settings: новое значение действует сразу
        get_settings.cache_clear()
    if model:
        for hook in on_model_change:
            hook()
    return changed


def _model_clean(patch: dict[str, str | None], stored: dict[str, str]) -> dict[str, str | None]:
    """Поля выбора модели из запроса. Проверяет, что у выбранного варианта есть всё нужное."""
    out: dict[str, str | None] = {}
    for key in MODEL_KEYS:
        if key not in patch or patch[key] is None:
            continue
        value = str(patch[key]).strip()
        if value and key in MODEL_SECRETS and is_masked(value):
            continue
        if len(value) > 500:
            raise SettingsError(key, f"{LABELS[key]}: слишком длинное значение")
        if key == "llm_mode" and value and value not in MODEL_MODES:
            raise SettingsError(key, "Модель: выберите облако, Yandex AI Studio или локальную модель")
        if key == "llm_local_url" and value:
            parts = urlsplit(value)
            if parts.scheme not in ("http", "https") or not parts.netloc:
                raise SettingsError(key, f"{LABELS[key]}: нужен адрес вида http://сервер:порт/v1")
            value = value.rstrip("/")
        out[key] = value or None
    merged = dict(stored)
    merged.update({k: v for k, v in out.items()})
    mode = merged.get("llm_mode") or "cloud"
    if "llm_mode" in out or any(k in out for k in MODEL_KEYS):
        if mode == "local":
            if not merged.get("llm_local_url"):
                raise SettingsError("llm_local_url", "Для локальной модели нужен адрес сервера, например http://сервер:11434/v1")
            if not merged.get("llm_local_model"):
                raise SettingsError("llm_local_model", "Для локальной модели нужно имя модели на сервере, например qwen2.5:7b")
        if mode == "yandex":
            if not merged.get("yandex_folder"):
                raise SettingsError("yandex_folder", "Для Yandex AI Studio нужен идентификатор каталога")
            if not merged.get("yandex_key"):
                raise SettingsError("yandex_key", "Для Yandex AI Studio нужен API-ключ")
    return out
