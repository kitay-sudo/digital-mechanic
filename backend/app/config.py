"""Настройки сервера. Всё, что зависит от окружения, читается из переменных (.env).

Адреса внешних сервисов (F6 ТЗ) меняются без правки кода: MOCK_ML_URL и MOCK_TOIR_URL.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
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
    price_currency: str
    usd_rate: float
    # Правила
    confidence_min: float
    max_agent_steps: int

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
    return Settings(
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
        price_currency=os.environ.get("PRICE_CURRENCY", "USD").upper(),
        usd_rate=_float("USD_RATE", 0.0),
        confidence_min=_float("CONFIDENCE_MIN", 0.5),
        max_agent_steps=int(_float("MAX_AGENT_STEPS", 10)),
    )
