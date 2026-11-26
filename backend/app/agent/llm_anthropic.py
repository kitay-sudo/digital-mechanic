"""Claude через официальный SDK Anthropic.

Ключ читается SDK из окружения (ANTHROPIC_API_KEY). Инструменты объявлены со
strict-схемами, итоговый ответ ограничен JSON-схемой (output_config.format).
"""
from __future__ import annotations

import anthropic

from .llm import LLMError, LLMResponse, ToolCall

FALLBACK_BETA = "server-side-fallback-2026-07-01"


class AnthropicLLM:
    name = "anthropic"
    is_mock = False

    def __init__(self, model: str, effort: str, fallbacks: bool):
        self.model = model
        self.effort = effort
        self.fallbacks = fallbacks
        self.client = anthropic.AsyncAnthropic()

    async def complete(self, system: str, messages: list[dict], tools: list[dict], schema: dict) -> LLMResponse:
        params = dict(
            model=self.model,
            max_tokens=16000,
            system=system,
            messages=messages,
            tools=[{**tool, "strict": True} for tool in tools],
            thinking={"type": "adaptive"},
            output_config={"effort": self.effort, "format": {"type": "json_schema", "schema": schema}},
            cache_control={"type": "ephemeral"},
        )
        try:
            if self.fallbacks:
                # При отказе по правилам безопасности API сам повторит запрос на запасной модели.
                response = await self.client.beta.messages.create(betas=[FALLBACK_BETA], fallbacks="default", **params)
            else:
                response = await self.client.messages.create(**params)
        except anthropic.AuthenticationError as exc:
            raise LLMError("Ключ модели не принят. Проверьте ANTHROPIC_API_KEY.") from exc
        except anthropic.PermissionDeniedError as exc:
            raise LLMError("У ключа модели нет доступа к этой модели.") from exc
        except anthropic.NotFoundError as exc:
            raise LLMError(f"Модель {self.model} не найдена. Проверьте LLM_MODEL.") from exc
        except anthropic.RateLimitError as exc:
            raise LLMError("Модель перегружена запросами. Повторите через минуту.") from exc
        except anthropic.BadRequestError as exc:
            raise LLMError(f"Модель не приняла запрос: {exc.message}") from exc
        except anthropic.APIStatusError as exc:
            raise LLMError(f"Ошибка сервиса модели (код {exc.status_code}). Повторите запрос.") from exc
        except anthropic.APIConnectionError as exc:
            raise LLMError("Нет связи с сервисом модели. Проверьте сеть.") from exc

        if response.stop_reason == "refusal":
            raise LLMError("Модель отказалась отвечать на этот запрос.")
        if response.stop_reason == "max_tokens":
            raise LLMError("Ответ модели оборвался по длине. Задайте вопрос уже.")

        tool_calls = [
            ToolCall(id=block.id, name=block.name, input=dict(block.input))
            for block in response.content if block.type == "tool_use"
        ]
        text = "".join(block.text for block in response.content if block.type == "text")
        usage = response.usage
        cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
        cache_write = getattr(usage, "cache_creation_input_tokens", 0) or 0
        return LLMResponse(
            content=response.content,  # блоки (включая thinking) возвращаются модели без изменений
            text=text,
            tool_calls=tool_calls,
            input_tokens=(usage.input_tokens or 0) + cache_write,
            output_tokens=usage.output_tokens or 0,
            cache_read_tokens=cache_read,
            model=response.model,
        )
