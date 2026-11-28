"""Вызов инструментов через один JSON-объект.

Нужен моделям без надёжного встроенного вызова инструментов: локальным моделям за сервером
с форматом OpenAI. Модель каждый раз отвечает объектом из двух
полей: tool_calls (что вызвать) и answer (итоговый ответ по схеме). Форму объекта задаёт
JSON-схема, поэтому сервер с ограниченным декодированием не даст модели выйти за неё.
"""
from __future__ import annotations

import json
import re

from .llm import LLMError

PROTOCOL = """

Как вызывать инструменты в этом режиме. Встроенных инструментов у тебя нет. Каждый твой ответ — один JSON-объект \
с двумя полями: tool_calls и answer.
- Нужны данные: перечисли вызовы в tool_calls (name и input по схеме инструмента), answer оставь null. \
Результаты придут следующим сообщением. Независимые вызовы ставь в один ответ.
- Данных достаточно: tool_calls — пустой список, answer — итоговый ответ по схеме.
Не выдумывай результаты инструментов: до их получения фактов о проверке и страницах руководств у тебя нет.

Инструменты:
"""

_THINK = re.compile(r"<think>.*?</think>", re.DOTALL)


def system_with_tools(system: str, tools: list[dict]) -> str:
    catalog = json.dumps(
        [{"name": t["name"], "description": t["description"], "input_schema": t["input_schema"]} for t in tools],
        ensure_ascii=False, indent=1,
    )
    return system + PROTOCOL + catalog


def envelope(tools: list[dict], schema: dict) -> dict:
    """Схема ответа: список вызовов инструментов и итоговый ответ (или null)."""
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


def render(messages: list[dict]) -> str:
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
                # Текст в сообщении механика (рядом с фото) — это его сообщение, а не ответ модели.
                parts.append(block["text"] if message["role"] == "user" else f"[Твой предыдущий ответ]\n{block['text']}")
            elif kind == "image":
                parts.append("[Механик приложил фото. В этом режиме подключения снимок модели не передаётся: "
                             "скажи механику, что фото не видно, и попроси описать словами]")
    return "\n\n".join(parts)


def extract(raw: str) -> dict:
    """JSON-объект из текста ответа: без рассуждений в <think> и без обёртки ```json."""
    raw = _THINK.sub("", raw or "")
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end <= start:
        raise LLMError("Модель вернула ответ не в формате JSON.")
    try:
        data = json.loads(raw[start:end + 1])
    except ValueError as exc:
        raise LLMError("Модель вернула ответ не в формате JSON.") from exc
    if not isinstance(data, dict):
        raise LLMError("Модель вернула ответ не в формате JSON.")
    return data


def split(data: dict) -> tuple[list[dict], dict]:
    """Вызовы инструментов и итоговый ответ из объекта модели.

    Слабая модель может вернуть сразу ответ без обёртки: такой объект считается итоговым ответом.
    """
    if "tool_calls" not in data and "answer" not in data:
        return [], data
    calls = [c for c in data.get("tool_calls") or [] if isinstance(c, dict) and c.get("name")]
    answer = data.get("answer")
    return calls, answer if isinstance(answer, dict) else {}
