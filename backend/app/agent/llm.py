"""Слой модели: единый интерфейс, за которым стоит конкретный поставщик.

Агент не знает, какая модель отвечает. Поставщик выбирается переменной LLM_PROVIDER:
`anthropic` (Claude через официальный SDK) или `mock` (заглушка для работы без ключа).
Внутренний формат сообщений повторяет формат Messages API: список блоков
text / tool_use / tool_result.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


class LLMError(Exception):
    """Ошибка модели с текстом, который можно показать механику."""


@dataclass
class ToolCall:
    id: str
    name: str
    input: dict


@dataclass
class LLMResponse:
    content: list[Any]            # блоки ответа как есть, возвращаются модели без изменений
    text: str                     # итоговый текст (JSON по схеме), если инструменты не вызваны
    tool_calls: list[ToolCall] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    model: str = ""


class LLM(Protocol):
    name: str
    model: str
    is_mock: bool

    async def complete(self, system: str, messages: list[dict], tools: list[dict], schema: dict) -> LLMResponse: ...


def build_llm() -> LLM:
    from ..config import get_settings

    settings = get_settings()
    if settings.llm_provider == "anthropic":
        from .llm_anthropic import AnthropicLLM

        return AnthropicLLM(settings.llm_model, settings.llm_effort, settings.llm_fallbacks)
    from .llm_mock import MockLLM

    return MockLLM()
