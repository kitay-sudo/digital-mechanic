"""Модель за сервером с форматом OpenAI Chat Completions.

Главное назначение — локальная модель в контуре заказчика (Ollama, vLLM, llama.cpp): данные
проверок и вопросы механиков не уходят наружу. Тем же слоем подключается любая модель у шлюза
с форматом OpenAI.

Два способа вызова инструментов (LLM_TOOLS):
- json (по умолчанию): модель отвечает одним JSON-объектом «вызовы или итоговый ответ», форму
  задаёт JSON-схема. Надёжно для локальных моделей: сервер с ограниченным декодированием не даст
  выйти за схему. См. json_protocol.py.
- native: встроенный вызов функций (tools / tool_calls). Для моделей и серверов, где он работает
  вместе со схемой ответа.

Как задаётся форма ответа (LLM_STRUCTURED): schema — response_format с JSON-схемой; json —
response_format json_object и схема в тексте инструкции; off — только схема в тексте инструкции.
"""
from __future__ import annotations

import json
import uuid

import httpx

from . import json_protocol
from .llm import LLMError, LLMResponse, ToolCall

SCHEMA_NOTE = "\n\nОтвет верни одним JSON-объектом строго по этой JSON-схеме, без текста вокруг:\n"


class OpenAICompatLLM:
    name = "openai"
    is_mock = False

    def __init__(self, model: str, base_url: str, api_key: str = "", tools_mode: str = "json",
                 structured: str = "schema", max_tokens: int = 6000, temperature: float | None = 0.0,
                 timeout: float = 600.0, project: str = "", transport: httpx.AsyncBaseTransport | None = None):
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.tools_mode = tools_mode if tools_mode in ("json", "native") else "json"
        self.structured = structured if structured in ("schema", "json", "off") else "schema"
        self.max_tokens = max_tokens
        self.temperature = temperature
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        if project:
            headers["OpenAI-Project"] = project
        self.client = httpx.AsyncClient(base_url=self.base_url, headers=headers, timeout=timeout, transport=transport)

    # --- запрос ---
    def _format(self, name: str, schema: dict, system: str) -> tuple[dict | None, str]:
        """Параметр response_format и инструкция с учётом того, что умеет сервер."""
        if self.structured == "schema":
            return {"type": "json_schema", "json_schema": {"name": name, "strict": True, "schema": schema}}, system
        note = SCHEMA_NOTE + json.dumps(schema, ensure_ascii=False)
        return ({"type": "json_object"} if self.structured == "json" else None), system + note

    @staticmethod
    def _native_messages(system: str, messages: list[dict]) -> list[dict]:
        out: list[dict] = [{"role": "system", "content": system}]
        for message in messages:
            content = message["content"]
            if isinstance(content, str):
                out.append({"role": message["role"], "content": content})
                continue
            text = "".join(b.get("text", "") for b in content if b.get("type") == "text")
            calls = [
                {"id": b["id"], "type": "function",
                 "function": {"name": b["name"], "arguments": json.dumps(b["input"], ensure_ascii=False)}}
                for b in content if b.get("type") == "tool_use"
            ]
            results = [b for b in content if b.get("type") == "tool_result"]
            if calls or (text and message["role"] == "assistant"):
                entry: dict = {"role": "assistant", "content": text or None}
                if calls:
                    entry["tool_calls"] = calls
                out.append(entry)
            for block in results:
                out.append({"role": "tool", "tool_call_id": block["tool_use_id"], "content": block["content"]})
        return out

    def _body(self, system: str, messages: list[dict], tools: list[dict], schema: dict) -> dict:
        body: dict = {"model": self.model, "max_tokens": self.max_tokens}
        if self.temperature is not None:
            body["temperature"] = self.temperature
        if self.tools_mode == "native":
            response_format, system = self._format("answer", schema, system)
            body["messages"] = self._native_messages(system, messages)
            body["tools"] = [
                {"type": "function",
                 "function": {"name": t["name"], "description": t["description"], "parameters": t["input_schema"]}}
                for t in tools
            ]
            body["tool_choice"] = "auto"
        else:
            response_format, system = self._format(
                "agent_step", json_protocol.envelope(tools, schema), json_protocol.system_with_tools(system, tools)
            )
            body["messages"] = [
                {"role": "system", "content": system},
                {"role": "user", "content": json_protocol.render(messages)},
            ]
        if response_format:
            body["response_format"] = response_format
        return body

    async def _post(self, body: dict) -> dict:
        try:
            response = await self.client.post("/chat/completions", json=body)
        except httpx.TimeoutException as exc:
            raise LLMError("Модель не ответила за отведённое время. Повторите запрос.") from exc
        except httpx.HTTPError as exc:
            raise LLMError(f"Нет связи с сервером модели по адресу {self.base_url}. Проверьте LLM_BASE_URL.") from exc
        if response.status_code == 401:
            raise LLMError("Ключ модели не принят. Проверьте LLM_API_KEY.")
        if response.status_code == 404:
            raise LLMError(f"Модель {self.model} не найдена на сервере. Проверьте LLM_MODEL и LLM_BASE_URL.")
        if response.status_code == 429:
            raise LLMError("Модель перегружена запросами. Повторите через минуту.")
        if response.status_code >= 400:
            detail = response.text[:300]
            try:
                error = response.json().get("error")
                detail = (error.get("message") if isinstance(error, dict) else str(error)) or detail
            except (ValueError, AttributeError):
                pass
            if response.status_code == 400:
                raise LLMError(f"Сервер модели не принял запрос: {detail[:300]}")
            raise LLMError(f"Ошибка сервера модели (код {response.status_code}). Повторите запрос.")
        try:
            return response.json()
        except ValueError as exc:
            raise LLMError("Сервер модели вернул непонятный ответ.") from exc

    # --- ответ ---
    async def complete(self, system: str, messages: list[dict], tools: list[dict], schema: dict) -> LLMResponse:
        if not self.model:
            raise LLMError("Не задана модель. Укажите LLM_MODEL.")
        data = await self._post(self._body(system, messages, tools, schema))
        try:
            choice = data["choices"][0]
            message = choice["message"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError("Сервер модели вернул ответ без текста.") from exc
        if choice.get("finish_reason") == "length":
            raise LLMError("Ответ модели оборвался по длине. Задайте вопрос уже.")

        usage = data.get("usage") or {}
        cached = (usage.get("prompt_tokens_details") or {}).get("cached_tokens") or 0
        common = dict(
            input_tokens=max(0, (usage.get("prompt_tokens") or 0) - cached),
            output_tokens=usage.get("completion_tokens") or 0,
            cache_read_tokens=cached,
            model=data.get("model") or self.model,
        )
        text = message.get("content") or ""

        if self.tools_mode == "native":
            raw_calls = message.get("tool_calls") or []
            if raw_calls:
                tool_calls = []
                for call in raw_calls:
                    function = call.get("function") or {}
                    arguments = function.get("arguments") or "{}"
                    try:
                        parsed = json.loads(arguments) if isinstance(arguments, str) else dict(arguments)
                    except ValueError:
                        parsed = {}
                    tool_calls.append(ToolCall(id=call.get("id") or f"oa_{uuid.uuid4().hex[:12]}",
                                               name=function.get("name", ""), input=parsed))
                content = [{"type": "tool_use", "id": c.id, "name": c.name, "input": c.input} for c in tool_calls]
                return LLMResponse(content=content, text="", tool_calls=tool_calls, **common)
            answer = json.dumps(json_protocol.extract(text), ensure_ascii=False)
            return LLMResponse(content=[{"type": "text", "text": answer}], text=answer, **common)

        calls, answer_data = json_protocol.split(json_protocol.extract(text))
        if calls:
            tool_calls = [ToolCall(id=f"oa_{uuid.uuid4().hex[:12]}", name=c["name"], input=dict(c.get("input") or {}))
                          for c in calls]
            content = [{"type": "tool_use", "id": c.id, "name": c.name, "input": c.input} for c in tool_calls]
            return LLMResponse(content=content, text="", tool_calls=tool_calls, **common)
        answer = json.dumps(answer_data, ensure_ascii=False)
        return LLMResponse(content=[{"type": "text", "text": answer}], text=answer, **common)
