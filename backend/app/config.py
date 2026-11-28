"""Настройки сервера. Всё, что зависит от окружения, читается из переменных (.env).

Адреса внешних сервисов (F6 ТЗ) меняются без правки кода: MOCK_ML_URL и MOCK_TOIR_URL.
"""
from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass, replace
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # корень репозитория


def _path(name: str, default: Path) -> Path:
    value = os.environ.get(name)
    return Path(value) if value else default


def _float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


def _flag(name: str, default: bool = True) -> bool:
    value = os.environ.get(name)
    if value is None or not value.strip():
        return default
    return value.strip().lower() not in ("0", "false", "no", "off")


@dataclass(frozen=True)
class Settings:
    # Внешние сервисы
    ml_url: str
    toir_url: str
    # Данные парка и справочники
    fleet_path: Path
    fault_types_path: Path
    manuals_config: Path
    conflicts_config: Path
    # База знаний вне Git: PDF и индекс
    kb_dir: Path
    # Данные приложения: чат, заявки, журнал
    data_dir: Path
    # Модель
    llm_provider: str
    llm_model: str
    llm_effort: str
    llm_fallbacks: bool
    # Сервер с форматом OpenAI (локальная модель): адрес, ключ, способ вызова инструментов и формы ответа
    llm_base_url: str
    llm_api_key: str
    llm_project: str
    llm_tools: str
    llm_structured: str
    llm_max_tokens: int
    llm_temperature: float | None
    llm_timeout: float
    # Выключатели возможностей слоя Claude на случай, если шлюз их не принимает
    llm_strict_tools: bool
    llm_thinking: bool
    llm_cache: bool
    # Цены для журнала стоимости
    price_input: float
    price_output: float
    price_cache_read: float
    price_cache_write: float
    price_currency: str
    usd_rate: float
    # Правила
    confidence_min: float
    max_agent_steps: int
    # Куда сообщать администратору о вопросах без ответа в руководстве (пусто — только журнал)
    alert_webhook_url: str
    # Распознавание речи на сервере (протокол OpenAI). Пустой адрес — распознаёт браузер
    stt_base_url: str
    stt_api_key: str
    stt_model: str
    stt_price_per_min: float
    # Доступ к внешним сервисам: токен (Authorization: Bearer) и кто принимает заявки (clients.py)
    ml_token: str = ""
    toir_token: str = ""
    ticket_sink: str = "toir"
    # Какую модель выбрал администратор: cloud — как в .env, yandex — Yandex AI Studio, local — сервер в контуре
    llm_mode: str = "cloud"

    @property
    def pdf_dir(self) -> Path:
        return self.kb_dir / "pdf"

    @property
    def index_path(self) -> Path:
        return self.kb_dir / "index.sqlite"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "app.sqlite"


@lru_cache
def get_settings() -> Settings:
    provider = os.environ.get("LLM_PROVIDER", "").strip().lower()
    if not provider:
        # Без ключа сервер работает на заглушке модели.
        provider = "anthropic" if os.environ.get("ANTHROPIC_API_KEY") else "mock"
    settings = Settings(
        ml_url=os.environ.get("MOCK_ML_URL", "http://127.0.0.1:8001").rstrip("/"),
        toir_url=os.environ.get("MOCK_TOIR_URL", "http://127.0.0.1:8002").rstrip("/"),
        fleet_path=_path("FLEET_DATA_PATH", ROOT / "mocks" / "data" / "vehicles.json"),
        fault_types_path=_path("FAULT_TYPES_PATH", ROOT / "mocks" / "data" / "fault_types.json"),
        manuals_config=_path("MANUALS_CONFIG", ROOT / "config" / "manuals.json"),
        conflicts_config=_path("CONFLICTS_CONFIG", ROOT / "config" / "conflicts.json"),
        kb_dir=_path("KB_DIR", ROOT / "knowledge"),
        data_dir=_path("DATA_DIR", ROOT / "data"),
        llm_provider=provider,
        llm_model=os.environ.get(
            "LLM_MODEL", {"mock": "mock-llm", "openai": ""}.get(provider, "claude-opus-5-5")
        ),
        llm_effort=os.environ.get("LLM_EFFORT", "medium"),
        llm_fallbacks=os.environ.get("LLM_FALLBACKS", "1") not in ("0", "false", "no"),
        llm_base_url=os.environ.get("LLM_BASE_URL", "http://127.0.0.1:11434/v1").rstrip("/"),
        llm_api_key=os.environ.get("LLM_API_KEY", ""),
        llm_project=os.environ.get("LLM_PROJECT", ""),
        llm_tools=os.environ.get("LLM_TOOLS", "json").strip().lower(),
        llm_structured=os.environ.get("LLM_STRUCTURED", "schema").strip().lower(),
        llm_max_tokens=int(_float("LLM_MAX_TOKENS", 16000 if provider == "anthropic" else 6000)),
        llm_temperature=None if os.environ.get("LLM_TEMPERATURE", "0").strip() == "" else _float("LLM_TEMPERATURE", 0.0),
        llm_timeout=_float("LLM_TIMEOUT", 600.0),
        llm_strict_tools=_flag("LLM_STRICT_TOOLS"),
        llm_thinking=_flag("LLM_THINKING"),
        llm_cache=_flag("LLM_CACHE"),
        price_input=_float("PRICE_INPUT_PER_MTOK", 4.0),
        price_output=_float("PRICE_OUTPUT_PER_MTOK", 20.0),
        price_cache_read=_float("PRICE_CACHE_READ_PER_MTOK", 0.2),
        # Запись в кэш у Anthropic стоит 1,25 цены входа, если своя цена не задана.
        price_cache_write=_float("PRICE_CACHE_WRITE_PER_MTOK", _float("PRICE_INPUT_PER_MTOK", 4.0) * 1.25),
        price_currency=os.environ.get("PRICE_CURRENCY", "USD").upper(),
        usd_rate=_float("USD_RATE", 0.0),
        confidence_min=_float("CONFIDENCE_MIN", 0.5),
        max_agent_steps=int(_float("MAX_AGENT_STEPS", 10)),
        alert_webhook_url=os.environ.get("ALERT_WEBHOOK_URL", "").strip(),
        stt_base_url=os.environ.get("STT_BASE_URL", "").strip(),
        # По умолчанию тот же ключ, что у модели: у ProxyAPI один ключ на все модели.
        stt_api_key=os.environ.get("STT_API_KEY") or os.environ.get("LLM_API_KEY") or os.environ.get("ANTHROPIC_API_KEY", ""),
        stt_model=os.environ.get("STT_MODEL", "gpt-4o-mini-transcribe").strip(),
        stt_price_per_min=_float("STT_PRICE_PER_MIN", 0.0),
        ml_token=os.environ.get("ML_API_TOKEN", "").strip(),
        toir_token=os.environ.get("TOIR_API_TOKEN", "").strip(),
        ticket_sink=os.environ.get("TICKET_SINK", "toir").strip() or "toir",
    )
    return _with_overrides(settings)


# Настройки подключений, которые администратор задал в интерфейсе или через API (integrations.py).
# Хранятся в базе и перекрывают .env. После их изменения кэш get_settings сбрасывается.
OVERRIDABLE = ("ml_url", "toir_url", "alert_webhook_url", "ml_token", "toir_token")
OVERRIDE_PREFIX = "integration."
# Выбор модели на экране «Подключения»: вариант и его поля (ключи хранятся так же, в базе)
MODEL_KEYS = ("llm_mode", "llm_local_url", "llm_local_model", "llm_local_key", "yandex_folder", "yandex_key", "yandex_model")
MODEL_MODES = ("cloud", "yandex", "local")
YANDEX_URL = "https://ai.api.cloud.yandex.net/v1"
YANDEX_DEFAULT_MODEL = "yandexgpt/latest"


def yandex_model_uri(folder: str, model: str) -> str:
    model = (model or YANDEX_DEFAULT_MODEL).strip()
    return model if model.startswith("gpt://") else f"gpt://{folder.strip()}/{model}"


def model_patch(settings: Settings, values: dict[str, str]) -> dict:
    """Поля модели по выбору администратора. Пустой выбор или нехватка полей — модель из .env."""
    mode = (values.get("llm_mode") or "cloud").strip()
    max_tokens = min(settings.llm_max_tokens, 6000)
    if mode == "local" and values.get("llm_local_url") and values.get("llm_local_model"):
        # Локальная модель бесплатна по токенам: стоимость считается по железу, а не по ценам облака
        return {"llm_mode": "local", "llm_provider": "openai", "llm_base_url": values["llm_local_url"].rstrip("/"),
                "llm_model": values["llm_local_model"].strip(), "llm_api_key": values.get("llm_local_key") or "",
                "llm_project": "", "llm_max_tokens": max_tokens,
                "price_input": 0.0, "price_output": 0.0, "price_cache_read": 0.0, "price_cache_write": 0.0}
    if mode == "yandex" and values.get("yandex_folder") and values.get("yandex_key"):
        folder = values["yandex_folder"].strip()
        out = {"llm_mode": "yandex", "llm_provider": "openai", "llm_base_url": YANDEX_URL,
               "llm_model": yandex_model_uri(folder, values.get("yandex_model") or ""),
               "llm_api_key": values["yandex_key"], "llm_project": folder, "llm_max_tokens": max_tokens,
               # Схему ответа сервис может не принять: «ответ в JSON» и схема в инструкции работают шире
               "llm_structured": "json"}
        price_in, price_out = os.environ.get("YANDEX_PRICE_INPUT_PER_MTOK"), os.environ.get("YANDEX_PRICE_OUTPUT_PER_MTOK")
        if price_in and price_out:
            out.update(price_input=float(price_in), price_output=float(price_out), price_cache_read=0.0,
                       price_cache_write=float(price_in))
        return out
    return {}


def _with_overrides(settings: Settings) -> Settings:
    path = settings.db_path
    if not path.exists():
        return settings
    try:
        con = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
        try:
            rows = con.execute("SELECT key, value FROM app_settings WHERE key LIKE ?", (OVERRIDE_PREFIX + "%",)).fetchall()
        finally:
            con.close()
    except sqlite3.Error:
        return settings  # таблицы ещё нет: настройки только из .env
    values = {key[len(OVERRIDE_PREFIX):]: value for key, value in rows}
    patch = {k: (values[k].rstrip("/") if k.endswith("_url") else values[k]) for k in OVERRIDABLE if k in values}
    patch.update(model_patch(settings, values))
    return replace(settings, **patch) if patch else settings
