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


@dataclass(frozen=True)
class Settings:
    # Внешние сервисы
    ml_url: str
    toir_url: str
    # Данные парка и справочники
    fleet_path: Path
    fault_types_path: Path
    manuals_config: Path
    # База знаний вне Git: PDF и индекс
    kb_dir: Path
    # Данные приложения: чат, заявки, журнал
    data_dir: Path
    # Модель
    llm_provider: str
    llm_model: str
    llm_effort: str
    llm_fallbacks: bool
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
        kb_dir=_path("KB_DIR", ROOT / "knowledge"),
        data_dir=_path("DATA_DIR", ROOT / "data"),
        llm_provider=provider,
        llm_model=os.environ.get("LLM_MODEL", "claude-opus-5-5" if provider == "anthropic" else "mock-llm"),
        llm_effort=os.environ.get("LLM_EFFORT", "medium"),
        llm_fallbacks=os.environ.get("LLM_FALLBACKS", "1") not in ("0", "false", "no"),
        price_input=_float("PRICE_INPUT_PER_MTOK", 4.0),
        price_output=_float("PRICE_OUTPUT_PER_MTOK", 20.0),
        price_cache_read=_float("PRICE_CACHE_READ_PER_MTOK", 0.2),
        price_currency=os.environ.get("PRICE_CURRENCY", "USD").upper(),
        usd_rate=_float("USD_RATE", 0.0),
        confidence_min=_float("CONFIDENCE_MIN", 0.5),
        max_agent_steps=int(_float("MAX_AGENT_STEPS", 10)),
    )
