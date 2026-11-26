"""Проверка ключа и шлюза перед прогоном: какие возможности слоя модели принимает сервис.

    python -m eval.preflight

Делает несколько коротких запросов к модели из настроек (.env) и печатает, что прошло. Если
какая-то возможность не принята, подсказывает переменную, которой её выключить. Запросы короткие,
стоимость проверки — доли рубля.
"""
from __future__ import annotations

import asyncio
import sys

from app.agent.llm import LLMError
from app.config import get_settings

TOOL = {
    "name": "get_number",
    "description": "Возвращает число. Вызови его.",
    "input_schema": {"type": "object", "properties": {"reason": {"type": "string"}}, "required": ["reason"],
                     "additionalProperties": False},
}
SCHEMA = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"], "additionalProperties": False}
USER = [{"role": "user", "content": "Ответь одним словом: готово."}]


async def anthropic_checks(settings) -> list[tuple[str, bool, str, str]]:
    import anthropic

    from app.agent.llm_anthropic import FALLBACK_BETA

    client = anthropic.AsyncAnthropic()
    base = dict(model=settings.llm_model, max_tokens=256, messages=USER)
    steps = [
        ("Ключ, адрес и модель", "", lambda: client.messages.create(**base)),
        ("Уровень усилий (effort)", "LLM_EFFORT=off",
         lambda: client.messages.create(**base, output_config={"effort": settings.llm_effort})),
        ("Рассуждения (thinking: adaptive)", "LLM_THINKING=off",
         lambda: client.messages.create(**{**base, "max_tokens": 2000}, thinking={"type": "adaptive"})),
        ("Строгие схемы инструментов (strict)", "LLM_STRICT_TOOLS=0",
         lambda: client.messages.create(**base, tools=[{**TOOL, "strict": True}])),
        ("Ответ по JSON-схеме (output_config.format)", "LLM_STRUCTURED=off",
         lambda: client.messages.create(**base, output_config={"format": {"type": "json_schema", "schema": SCHEMA}})),
        ("Кэш запроса (cache_control)", "LLM_CACHE=0",
         lambda: client.messages.create(**base, cache_control={"type": "ephemeral"})),
        ("Запасная модель при отказе (fallbacks)", "LLM_FALLBACKS=0",
         lambda: client.beta.messages.create(**base, betas=[FALLBACK_BETA], fallbacks="default")),
    ]
    results = []
    for title, fix, call in steps:
        try:
            response = await call()
            results.append((title, True, f"модель {response.model}", fix))
        except anthropic.APIStatusError as exc:
            results.append((title, False, f"код {exc.status_code}: {str(exc.message)[:200]}", fix))
        except anthropic.APIConnectionError as exc:
            results.append((title, False, f"нет связи: {exc}", fix))
        if not results[-1][1] and title.startswith("Ключ"):
            break  # без ключа и модели остальное проверять нет смысла
    return results


async def generic_check(settings) -> list[tuple[str, bool, str, str]]:
    """Для остальных слоёв: один полный вызов через наш слой с инструментом и схемой."""
    from app.agent.llm import build_llm

    llm = build_llm()
    try:
        response = await llm.complete("Ты проверяешь связь. Сразу дай итоговый ответ.", USER, [TOOL], SCHEMA)
        return [("Запрос через слой модели", True, f"модель {response.model}, ответ {response.text[:80]}", "")]
    except LLMError as exc:
        return [("Запрос через слой модели", False, str(exc), "проверьте LLM_BASE_URL, LLM_MODEL, LLM_STRUCTURED")]


async def main() -> int:
    settings = get_settings()
    print(f"Слой: {settings.llm_provider}, модель: {settings.llm_model}\n")
    if settings.llm_provider == "mock":
        print("Работает заглушка модели. Задайте LLM_PROVIDER и ключ в .env.")
        return 1
    checks = await (anthropic_checks(settings) if settings.llm_provider == "anthropic" else generic_check(settings))
    advice = []
    for title, ok, detail, fix in checks:
        print(f"{'ok  ' if ok else 'НЕТ '} {title}: {detail}")
        if not ok and fix:
            advice.append(fix)
    if advice:
        print("\nЧто поправить в .env:")
        for line in advice:
            print(f"  {line}")
    else:
        print("\nВсе возможности приняты, можно запускать прогон сценариев.")
    return 1 if any(not ok for _, ok, _, _ in checks) else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
