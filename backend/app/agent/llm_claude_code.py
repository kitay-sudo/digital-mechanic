"""Claude через локальный Claude Code (командная строка). Только для разработки.

Нужен, чтобы проверить агента на настоящей модели без ключа API: используется вход пользователя
в Claude Code на этой машине (`claude auth login`). На стенде и в Docker этот слой не работает,
там модель подключается по ключу (LLM_PROVIDER=anthropic).

У командной строки нет вызова своих инструментов, поэтому протокол такой: модель отвечает одним
JSON-объектом. Либо список вызовов инструментов, либо итоговый ответ по схеме. Форму объекта
задаёт JSON-схема (--json-schema), инструменты выполняет наш код, как и с другими слоями модели.
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path

from .llm import LLMError, LLMResponse, ToolCall

TIMEOUT = 300

PROTOCOL = """

Как вызывать инструменты в этом режиме. Встроенных инструментов у тебя нет. Каждый твой ответ — один JSON-объект \
с двумя полями: tool_calls и answer.
- Нужны данные: перечисли вызовы в tool_calls (name и input по схеме инструмента), answer оставь null. \
Результаты придут следующим сообщением. Независимые вызовы ставь в один ответ.
- Данных достаточно: tool_calls — пустой список, answer — итоговый ответ по схеме.
Не выдумывай результаты инструментов: до их получения фактов о проверке и страницах руководств у тебя нет.

Инструменты:
"""


def _executable() -> str:
    explicit = os.environ.get("CLAUDE_CODE_BIN")
    if explicit:
        return explicit
    found = shutil.which("claude")
    if not found:
        raise LLMError("Claude Code не найден. Установите его или задайте путь в CLAUDE_CODE_BIN.")
    # В Windows команда `claude` — обёртка .cmd, настоящий исполняемый файл лежит рядом.
    native = Path(found).parent / "node_modules" / "@anthropic-ai" / "claude-code" / "bin" / "claude.exe"
    return str(native) if native.exists() else found


def _envelope(tools: list[dict], schema: dict) -> dict:
    calls = [
        {
            "type": "object",
            "properties": {"name": {"type": "string", "enum": [tool["name"]]}, "input": tool["input_schema"]},
            "required": ["name", "input"],
            "additionalProperties": False,
        }
        for tool in tools
    ]
    return {
        "type": "object",
        "properties": {
            "tool_calls": {"type": "array", "items": {"anyOf": calls}},
            "answer": {"anyOf": [schema, {"type": "null"}]},
        },
        "required": ["tool_calls", "answer"],
        "additionalProperties": False,
    }


def _render(messages: list[dict]) -> str:
    """Диалог хода одним текстом: вызовы и результаты инструментов идут подписанными блоками."""
    names: dict[str, str] = {}
    parts: list[str] = []
    for message in messages:
        content = message["content"]
        if isinstance(content, str):
            parts.append(content)
            continue
        for block in content:
            kind = block.get("type")
            if kind == "tool_use":
                names[block["id"]] = block["name"]
                parts.append(f"[Ты вызвал инструмент {block['name']}]\n{json.dumps(block['input'], ensure_ascii=False)}")
            elif kind == "tool_result":
                name = names.get(block["tool_use_id"], "")
                mark = " (ошибка)" if block.get("is_error") else ""
                parts.append(f"[Результат инструмента {name}{mark}]\n{block['content']}")
            elif kind == "text" and block.get("text"):
                parts.append(f"[Твой предыдущий ответ]\n{block['text']}")
    return "\n\n".join(parts)


def _extract(raw: str) -> dict:
    """JSON-объект из текста ответа, если командная строка не вернула structured_output."""
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end <= start:
        raise LLMError("Модель вернула ответ не в формате JSON.")
    try:
        return json.loads(raw[start:end + 1])
    except ValueError as exc:
        raise LLMError("Модель вернула ответ не в формате JSON.") from exc


class ClaudeCodeLLM:
    name = "claude_code"
    is_mock = False

    def __init__(self, model: str, effort: str):
        self.model = model
        self.effort = effort
        self.workdir = Path(tempfile.gettempdir()) / "smithy-claude-code"
        self.workdir.mkdir(parents=True, exist_ok=True)

    def _run(self, system: str, prompt: str, schema: dict) -> dict:
        system_file = self.workdir / f"system-{uuid.uuid4().hex}.txt"
        system_file.write_text(system, encoding="utf-8")
        command = [
            _executable(), "-p", "--output-format", "json", "--model", self.model,
            "--tools", "", "--strict-mcp-config", "--no-session-persistence",
            "--system-prompt-file", str(system_file),
            "--json-schema", json.dumps(schema, ensure_ascii=True),
        ]
        try:
            done = subprocess.run(
                command, input=prompt.encode("utf-8"), capture_output=True, timeout=TIMEOUT, cwd=self.workdir,
            )
        except subprocess.TimeoutExpired as exc:
            raise LLMError("Модель не ответила за отведённое время. Повторите запрос.") from exc
        except OSError as exc:
            raise LLMError(f"Не удалось запустить Claude Code: {exc}") from exc
        finally:
            system_file.unlink(missing_ok=True)
        out = done.stdout.decode("utf-8", errors="replace").strip()
        try:
            return json.loads(out.splitlines()[-1]) if out else {}
        except ValueError as exc:
            detail = (done.stderr.decode("utf-8", errors="replace") or out)[:300]
            raise LLMError(f"Claude Code вернул непонятный ответ: {detail}") from exc

    async def complete(self, system: str, messages: list[dict], tools: list[dict], schema: dict) -> LLMResponse:
        catalog = json.dumps(
            [{"name": t["name"], "description": t["description"], "input_schema": t["input_schema"]} for t in tools],
            ensure_ascii=False, indent=1,
        )
        result = await asyncio.to_thread(
            self._run, system + PROTOCOL + catalog, _render(messages), _envelope(tools, schema)
        )
        if not result or result.get("is_error"):
            reason = str(result.get("result") or "пустой ответ")
            if "authenticate" in reason.lower() or "oauth" in reason.lower() or "login" in reason.lower():
                raise LLMError("Claude Code не вошёл в аккаунт. Выполните в терминале: claude auth login")
            raise LLMError(f"Claude Code вернул ошибку: {reason[:300]}")

        data = result.get("structured_output")
        if not isinstance(data, dict):
            data = _extract(str(result.get("result") or ""))

        usage = result.get("usage") or {}
        model = next(iter(result.get("modelUsage") or {}), self.model)
        common = dict(
            input_tokens=(usage.get("input_tokens") or 0) + (usage.get("cache_creation_input_tokens") or 0),
            output_tokens=usage.get("output_tokens") or 0,
            cache_read_tokens=usage.get("cache_read_input_tokens") or 0,
            model=model,
        )
        calls = [c for c in data.get("tool_calls") or [] if isinstance(c, dict) and c.get("name")]
        if calls:
            tool_calls = [ToolCall(id=f"cc_{uuid.uuid4().hex[:12]}", name=c["name"], input=dict(c.get("input") or {}))
                          for c in calls]
            content = [{"type": "tool_use", "id": c.id, "name": c.name, "input": c.input} for c in tool_calls]
            return LLMResponse(content=content, text="", tool_calls=tool_calls, **common)
        text = json.dumps(data.get("answer") or {}, ensure_ascii=False)
        return LLMResponse(content=[{"type": "text", "text": text}], text=text, **common)
