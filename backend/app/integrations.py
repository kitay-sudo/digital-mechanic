"""Настройки подключений: адреса ML-сервиса и ТОиР, веб-хук администратора, токены доступа.

Администратор задаёт их в интерфейсе или через /api/v1/settings/integrations. Значения хранятся
в базе и перекрывают .env (config._with_overrides). Пустое значение возвращает настройку из .env.
Секреты (токены, путь веб-хука, пароль в адресе) в ответе маскируются.
"""
from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit

from .config import OVERRIDABLE, OVERRIDE_PREFIX, get_settings
from .db import get_db

URL_FIELDS = ("ml_url", "toir_url", "alert_webhook_url")
SECRET_FIELDS = ("ml_token", "toir_token")
LABELS = {
    "ml_url": "Адрес ML-сервиса «НейроДВС»",
    "toir_url": "Адрес системы ТОиР",
    "alert_webhook_url": "Веб-хук администратора",
    "ml_token": "Токен ML-сервиса",
    "toir_token": "Токен ТОиР",
}
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
    return out


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
    for key, value in clean.items():
        db.set_value(OVERRIDE_PREFIX + key, value)
        changed.append(key)
    if changed:
        # Клиенты, правила и оповещения читают адреса из get_settings: новое значение действует сразу
        get_settings.cache_clear()
    return changed
