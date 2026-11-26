"""Claude через официальный SDK Anthropic.

Ключ и адрес читает SDK из окружения: ANTHROPIC_API_KEY и, для шлюза с тем же форматом запросов
(например, ProxyAPI), ANTHROPIC_BASE_URL. Инструменты объявлены со strict-схемами, итоговый ответ
ограничен JSON-схемой (output_config.format).

Каждую возможность можно выключить переменной окружения, если шлюз или модель её не принимает:
LLM_STRUCTURED=off, LLM_STRICT_TOOLS=0, LLM_THINKING=off, LLM_CACHE=0, LLM_FALLBACKS=0, LLM_EFFORT=off.
Какие из них принимает ваш ключ, показывает `python -m eval.preflight`.
"""
from __future__ import annotations

import json

import anthropic

from . import json_protocol
from .llm import LLMError, LLMResponse, ToolCall

FALLBACK_BETA = "server-side-fallback-2026-07-01"
SCHEMA_NOTE = "\n\nИтоговый ответ верни одним JSON-объектом строго по этой JSON-схеме, без текста вокруг:\n"


class AnthropicLLM:
    name = "anthropic"
    is_mock = False

    def __init__(self, model: str, effort: str, fallbacks: bool, structured: bool = True, strict_tools: bool = True,
                 thinking: bool = True, cache: bool = True, max_tokens: int = 16000, client=None):
        self.model = model
        self.effort = effort
        self.fallbacks = fallbacks
        self.structured = structured
        self.strict_tools = strict_tools
        self.thinking = thinking
        self.cache = cache
        self.max_tokens = max_tokens
        self.client = client or anthropic.AsyncAnthropic()

    def params(self, system: str, messages: list[dict], tools: list[dict], schema: dict) -> dict:
        output_config: dict = {} if self.effort in ("", "off") else {"effort": self.effort}
        if self.structured:
            output_config["format"] = {"type": "json_schema", "schema": schema}
        else:
            # Запасной режим: схема уходит в инструкцию, JSON достаём из текста ответа.
            system = system + SCHEMA_NOTE + json.dumps(schema, ensure_ascii=False)
        params = dict(
            model=self.model,
            max_tokens=self.max_tokens,
            system=system,
            messages=messages,
            tools=[{**tool, "strict": True} for tool in tools] if self.strict_tools else tools,
        )
        if output_config:
            params["output_config"] = output_config
        if self.thinking:
            params["thinking"] = {"type": "adaptive"}
        if self.cache:
            params["cache_control"] = {"type": "ephemeral"}
        return params

    async def complete(self, system: str, messages: list[dict], tools: list[dict], schema: dict) -> LLMResponse:
        params = self.params(system, messages, tools, schema)
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
            raise LLMError("Нет связи с сервисом модели. Проверьте сеть и ANTHROPIC_BASE_URL.") from exc

        if response.stop_reason == "refusal":
            raise LLMError("Модель отказалась отвечать на этот запрос.")
        if response.stop_reason == "max_tokens":
            raise LLMError("Ответ модели оборвался по длине. Задайте вопрос уже.")

        tool_calls = [
            ToolCall(id=block.id, name=block.name, input=dict(block.input))
            for block in response.content if block.type == "tool_use"
        ]
        text = "".join(block.text for block in response.content if block.type == "text")
        if not tool_calls and not self.structured:
            text = json.dumps(json_protocol.extract(text), ensure_ascii=False)
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
            cache_write_tokens=cache_write,
            model=response.model,
        )
