"""Вход и роли.

Механик выбирает себя в списке и набирает PIN, администратор входит по логину и паролю
(ADMIN_LOGIN, ADMIN_PASSWORD). Сессия — подписанная кука (HMAC-SHA256 на SECRET_KEY), httpOnly,
SameSite=Lax. Только администратору: журнал (/api/audit*), расход (/api/usage*), сводка смены и метрики,
механики и настройки подключений (/api/admin/*). Механику — парк, чат, руководства.

AUTH_REQUIRED=0 выключает проверку (тесты, локальная разработка). API для внешних систем (/api/v1)
закрыт своим ключом X-API-Key независимо от этого переключателя (api_v1.py). Действующий ключ
X-API-Key открывает и остальные маршруты: так работают служебные скрипты (eval) и интеграции.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import time
from http.cookies import SimpleCookie

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from . import mechanics
from .db import get_db

log = logging.getLogger("mechanic")

COOKIE = "dm_session"
MECHANIC_HOURS = 12   # смена
ADMIN_HOURS = 8
ADMIN_MAX_FAILS = 5
ADMIN_LOCK_SECONDS = 60

# Без входа: проверка сервера, общие настройки интерфейса, сам вход, документация API.
# /api/v1 закрыт ключом X-API-Key (api_v1.py).
PUBLIC = ("/api/health", "/api/config", "/api/docs", "/api/openapi.json")
PUBLIC_PREFIXES = ("/api/auth/", "/api/v1/", "/api/docs/")
ADMIN_PREFIXES = ("/api/audit", "/api/usage", "/api/admin/", "/api/shift-summary", "/api/metrics")


def _flag(name: str, default: bool) -> bool:
    value = os.environ.get(name, "").strip().lower()
    if not value:
        return default
    return value not in ("0", "false", "no", "off")


def required() -> bool:
    return _flag("AUTH_REQUIRED", True)


def admin_credentials() -> tuple[str, str]:
    return (os.environ.get("ADMIN_LOGIN", "").strip() or "admin", os.environ.get("ADMIN_PASSWORD", "") or "admin")


def demo_hint() -> str | None:
    return os.environ.get("DEMO_LOGIN_HINT", "").strip() or None


def api_keys() -> list[str]:
    """Ключи внешних систем из INTEGRATION_API_KEYS через запятую. Пусто — API выключен."""
    return [k.strip() for k in os.environ.get("INTEGRATION_API_KEYS", "").split(",") if k.strip()]


def key_valid(key: str | None) -> bool:
    if not key:
        return False
    return any(hmac.compare_digest(key.encode(), k.encode()) for k in api_keys())


def secret_key() -> bytes:
    """SECRET_KEY из .env. Если не задан — создаётся один раз и хранится в базе, чтобы вход не слетал при перезапуске."""
    value = os.environ.get("SECRET_KEY", "").strip()
    if value:
        return value.encode()
    db = get_db()
    stored = db.get_value("auth.secret_key")
    if not stored:
        stored = secrets.token_urlsafe(32)
        db.set_value("auth.secret_key", stored)
    return stored.encode()


def warn_defaults() -> None:
    if not required():
        log.warning("AUTH_REQUIRED=0: вход выключен, все экраны открыты без пароля. Только для разработки.")
        return
    if not os.environ.get("ADMIN_PASSWORD"):
        log.warning("ADMIN_LOGIN и ADMIN_PASSWORD не заданы: администратор входит как admin/admin. Задайте свои в .env.")
    if not os.environ.get("SECRET_KEY", "").strip():
        log.warning("SECRET_KEY не задан: ключ подписи сессий создан автоматически и хранится в базе. Задайте свой в .env.")


# --- подписанная кука ---
def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def sign(payload: dict) -> str:
    body = _b64(json.dumps(payload, separators=(",", ":")).encode())
    mac = hmac.new(secret_key(), body.encode(), hashlib.sha256).digest()
    return f"{body}.{_b64(mac)}"


def unsign(token: str) -> dict | None:
    try:
        body, mac = token.split(".", 1)
        expected = hmac.new(secret_key(), body.encode(), hashlib.sha256).digest()
        if not hmac.compare_digest(_unb64(mac), expected):
            return None
        payload = json.loads(_unb64(body))
    except (ValueError, TypeError):
        return None
    if not isinstance(payload, dict) or payload.get("exp", 0) < time.time():
        return None
    return payload


def session_from_cookie(header: str | None) -> dict | None:
    """Действующая сессия из заголовка Cookie. Сессия механика гаснет, если ему сменили PIN или отключили."""
    if not header:
        return None
    jar = SimpleCookie()
    try:
        jar.load(header)
    except Exception:
        return None
    morsel = jar.get(COOKIE)
    payload = unsign(morsel.value) if morsel else None
    if not payload:
        return None
    if payload.get("role") == "mechanic":
        if mechanics.repo().session_version(int(payload.get("mid", 0))) != payload.get("v"):
            return None
    elif payload.get("role") != "admin":
        return None
    return payload


def _secure(request: Request) -> bool:
    if _flag("COOKIE_SECURE", False):
        return True
    return request.headers.get("x-forwarded-proto", request.url.scheme) == "https"


def set_session(response: Response, request: Request, payload: dict, hours: int) -> None:
    payload = {**payload, "exp": int(time.time()) + hours * 3600}
    response.set_cookie(COOKIE, sign(payload), max_age=hours * 3600, httponly=True, samesite="lax",
                        secure=_secure(request), path="/")


# --- проверка доступа к маршрутам ---
def _public(path: str) -> bool:
    return path in PUBLIC or path.startswith(PUBLIC_PREFIXES)


def _admin_only(path: str) -> bool:
    return path.startswith(ADMIN_PREFIXES)


class AuthGuard:
    """ASGI-прослойка: пускает к /api/* только с действующей сессией нужной роли."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not scope["path"].startswith("/api/") or scope["method"] == "OPTIONS":
            return await self.app(scope, receive, send)
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
        path = scope["path"]
        if required() and not _public(path) and not key_valid(headers.get("x-api-key")):
            session = session_from_cookie(headers.get("cookie"))
            if session is None:
                return await _deny(401, "Войдите в систему: выберите себя в списке «Кто работает» и наберите PIN.",
                                   scope, receive, send)
            if _admin_only(path) and session["role"] != "admin":
                return await _deny(403, "Этот раздел только для администратора.", scope, receive, send)
        await self.app(scope, receive, send)


async def _deny(status: int, text: str, scope, receive, send) -> None:
    await JSONResponse({"detail": text}, status_code=status)(scope, receive, send)


# --- вход и выход ---
router = APIRouter(prefix="/api/auth", tags=["Вход"], include_in_schema=False)


def me_of(request: Request) -> dict:
    session = session_from_cookie(request.headers.get("cookie"))
    mechanic = None
    if session and session["role"] == "mechanic":
        mechanic = mechanics.repo().get(int(session["mid"]))
    return {
        "required": required(),
        "role": session["role"] if session else None,
        "mechanic": {k: mechanic[k] for k in ("id", "full_name", "level", "font_size")} if mechanic else None,
        "hint": demo_hint(),
    }


@router.get("/me")
async def me(request: Request):
    """Кто вошёл: роль, механик с его настройками. required=false — вход выключен (AUTH_REQUIRED=0)."""
    return me_of(request)


@router.get("/mechanics")
async def mechanic_list():
    """Список для экрана «Кто работает»: только работающие механики, только ФИО.
    На демонстрационном стенде (DEMO_SEED=1) у демо-механиков ещё и PIN — он виден прямо в строке."""
    repo = mechanics.repo()
    pins = repo.demo_pins()
    items = [{"id": m["id"], "full_name": m["full_name"], "demo_pin": pins.get(m["id"])}
             for m in repo.list(include_inactive=False)]
    return {"items": items, "hint": demo_hint()}


class MechanicLogin(BaseModel):
    mechanic_id: int
    pin: str = Field(min_length=1, max_length=8)


@router.post("/mechanic")
async def login_mechanic(req: MechanicLogin, request: Request):
    try:
        m = mechanics.repo().login(req.mechanic_id, req.pin.strip())
    except mechanics.MechanicError as exc:
        return JSONResponse({"detail": str(exc), **exc.extra}, status_code=exc.status)
    response = JSONResponse({"role": "mechanic", "mechanic": {k: m[k] for k in ("id", "full_name", "level", "font_size")}})
    set_session(response, request, {"role": "mechanic", "mid": m["id"], "v": m["version"]}, MECHANIC_HOURS)
    log.info("Вход механика: %s", m["full_name"])
    return response


class AdminLogin(BaseModel):
    login: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=200)


_admin_fails: dict[str, tuple[int, float]] = {}


@router.post("/admin")
async def login_admin(req: AdminLogin, request: Request):
    key = req.login.strip().lower()
    fails, locked_until = _admin_fails.get(key, (0, 0.0))
    moment = time.time()
    if locked_until > moment:
        wait = int(locked_until - moment + 0.999)
        raise HTTPException(429, f"Слишком много неверных попыток. Подождите {wait} с.")
    login, password = admin_credentials()
    ok = hmac.compare_digest(req.login.strip().encode(), login.encode()) & hmac.compare_digest(
        req.password.encode(), password.encode())
    if not ok:
        fails += 1
        if fails >= ADMIN_MAX_FAILS:
            _admin_fails[key] = (0, moment + ADMIN_LOCK_SECONDS)
            raise HTTPException(429, "Неверный логин или пароль 5 раз подряд. Вход закрыт на минуту.")
        _admin_fails[key] = (fails, 0.0)
        raise HTTPException(401, "Неверный логин или пароль.")
    _admin_fails.pop(key, None)
    response = JSONResponse({"role": "admin"})
    set_session(response, request, {"role": "admin"}, ADMIN_HOURS)
    log.info("Вход администратора")
    return response


@router.post("/logout")
async def logout():
    response = JSONResponse({"ok": True})
    response.delete_cookie(COOKIE, path="/")
    return response


def install(app) -> None:
    """Подключает вход: маршруты /api/auth и проверку доступа ко всем /api/*."""
    app.include_router(router)
    app.add_middleware(AuthGuard)
    warn_defaults()
