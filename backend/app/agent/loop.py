"""Ход агента: модель выбирает инструменты, код исполняет их и проверяет итоговый ответ."""
from __future__ import annotations

import json
import re
import time

from .. import conflicts, rules
from ..config import Settings
from ..kb.index import Index
from ..store import Store
from . import json_protocol, prompt
from .llm import LLM, LLMError
from .tools import ANSWER_SCHEMA, TOOLS, Emit, TurnContext, ensure_diagnosis, run_tool, submit_ticket

STEP_LABELS = {
    "tools": "Выбор инструмента и поиск",
    "ticket": "Формирование заявки",
    "answer": "Генерация ответа",
    "retry": "Повтор после проверки ссылок",
}
EMPTY_ANSWER = {"summary": "", "observations": [], "hypotheses": [], "checks": [], "repair": [],
                "limitations": [], "conflicts": [], "not_found": False}
HIDDEN_NOTE = "Часть ответа скрыта: её не удалось подтвердить страницей руководства."
MISMATCH_TEXT = ("Это ошибка модели диагностики, а не диагноз: по этому типу выводов о двигателе нет. "
                 "Повторите проверку или проведите дефектовку.")
KB_EMPTY_TEXT = ("Руководства на двигатель {engine} не загружены в базу знаний, поэтому ответить по ним сейчас нельзя. "
                 "Это настройка стенда, а не отсутствие инструкции: обратитесь к администратору.")
UNSOURCED_TEXT = ("Подтвердить ответ страницей руководства на этот двигатель не удалось. "
                  "Без страницы и цитаты агент фактов и нормативов не называет.")
CONFLICT_LEAD = "В руководствах есть расхождение, формулировки показаны ниже."


def _cost(settings: Settings, inp: int, out: int, cache: int) -> tuple[float, float]:
    """Стоимость вызова в валюте прайса и в рублях (без НДС)."""
    cost = (inp * settings.price_input + out * settings.price_output + cache * settings.price_cache_read) / 1_000_000
    rub = cost if settings.price_currency == "RUB" else cost * settings.usd_rate
    return cost, rub


def _history_block(messages: list[dict]) -> str:
    lines = []
    for m in messages[-8:]:
        if m["role"] == "user":
            lines.append(f"Механик: {m.get('text', '')}")
        else:
            lines.append(f"Агент: {prompt.render_for_history(m)}")
    return "\n".join(lines)


def _parse(text: str) -> dict:
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return {**EMPTY_ANSWER, **data}
    except ValueError:
        pass
    try:
        # JSON в обёртке ```json или с текстом вокруг: бывает, когда схема задана только в инструкции.
        return {**EMPTY_ANSWER, **json_protocol.extract(text)}
    except LLMError:
        return {**EMPTY_ANSWER, "summary": text.strip()}


async def run_turn(
    *, vehicle: dict, session_id: str, text: str, store: Store, index: Index, settings: Settings,
    llm: LLM, emit: Emit, confirmed_draft_id: str | None = None, warning_ack: bool = False,
    profile: dict | None = None,
) -> None:
    started = time.monotonic()
    vehicle_id = vehicle["vehicle_id"]
    turn_id = store.start_turn(vehicle_id, session_id)
    ctx = TurnContext(vehicle=vehicle, session_id=session_id, store=store, index=index, settings=settings, emit=emit,
                      confirmed_draft_id=confirmed_draft_id, warning_ack=warning_ack)
    await ensure_diagnosis(ctx)
    saved = store.analysis(vehicle_id, session_id)

    history = _history_block(store.messages(vehicle_id))
    user_message = store.add_message(vehicle_id, session_id, "user", {"text": text})
    await emit({"type": "user", "message": user_message})

    content = prompt.turn_context(vehicle, session_id, saved, profile)
    if history:
        content += "\n\n[Предыдущий диалог]\n" + history
    content += "\n\n[Сообщение механика]\n" + text
    messages: list[dict] = [{"role": "user", "content": content}]

    totals = {"input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 0, "cost": 0.0, "cost_rub": 0.0, "llm_calls": 0}
    answer, problems, retried, counter = None, [], False, 0
    first_problems: list[str] = []
    try:
        for _ in range(settings.max_agent_steps):
            call_started = time.monotonic()
            response = await llm.complete(prompt.SYSTEM, messages, TOOLS, ANSWER_SCHEMA)
            names = {c.name for c in response.tool_calls}
            if names & {"prepare_ticket", "submit_ticket"}:
                label = "ticket"
            elif names:
                label = "tools"
            else:
                label = "retry" if retried else "answer"
            cost, rub = _cost(settings, response.input_tokens, response.output_tokens, response.cache_read_tokens)
            store.log_llm_call(turn_id, STEP_LABELS[label], response.model or llm.model, response.input_tokens,
                               response.output_tokens, response.cache_read_tokens, rub,
                               int((time.monotonic() - call_started) * 1000))
            totals["input_tokens"] += response.input_tokens + response.cache_read_tokens
            totals["output_tokens"] += response.output_tokens
            totals["cache_read_tokens"] += response.cache_read_tokens
            totals["cost"] += cost
            totals["cost_rub"] += rub
            totals["llm_calls"] += 1

            if response.tool_calls:
                messages.append({"role": "assistant", "content": response.content})
                results = []
                for call in response.tool_calls:
                    counter += 1
                    result, is_error = await run_tool(ctx, call.name, call.input, f"s{counter}")
                    block = {"type": "tool_result", "tool_use_id": call.id, "content": result}
                    if is_error:
                        block["is_error"] = True
                    results.append(block)
                messages.append({"role": "user", "content": results})
                continue

            raw = _parse(response.text)
            answer, problems = ctx.verifier().verify_answer(raw)
            _cap(answer)
            if _unsourced(ctx, answer):
                problems.append(
                    "Ответ без ссылок: каждый факт из руководства должен стоять в checks или repair со страницей "
                    "и дословной цитатой. Если подтвердить нечем, поставь not_found: true и не называй фактов"
                )
            failed = ctx.assessment and ctx.assessment["outcome"] == "check_failed"
            if problems and not retried and not failed:
                first_problems = list(problems)
                # Одна попытка исправиться: модель видит, какие пункты не прошли сверку со страницей.
                retried = True
                messages.append({"role": "assistant", "content": response.content})
                messages.append({"role": "user", "content": (
                    "[Проверка системы] Часть ответа не прошла сверку с руководством:\n- " + "\n- ".join(problems[:8]) +
                    "\nИсправь ответ: цитаты копируй дословно из найденного текста, числа оставляй только те, что есть "
                    "на процитированной странице. Пункты, которые подтвердить нельзя, убери или перенеси в гипотезы "
                    "без чисел. Если данных в руководстве нет, скажи об этом."
                )})
                continue
            break
        else:
            raise LLMError("Агент сделал слишком много шагов и не закончил ответ. Повторите запрос.")

        # Подтверждённую механиком заявку отправляем в любом случае: это его решение, а не модели.
        if confirmed_draft_id and ctx.ticket is None:
            sent_error = next((s for s in ctx.steps if s["tool"] == "submit_ticket" and s["status"] == "error"), None)
            if sent_error is None:
                counter += 1
                await submit_ticket(ctx, {"draft_id": confirmed_draft_id}, f"s{counter}")
    except LLMError as exc:
        store.finish_turn(turn_id, "error", int((time.monotonic() - started) * 1000), False)
        await emit({"type": "error", "text": str(exc)})
        await emit({"type": "done", "usage": _usage(totals, started, llm)})
        return

    answer = answer or dict(EMPTY_ANSWER)
    _apply_conflicts(ctx, answer, text)
    payload = _build_message(ctx, answer, problems, confirmed_draft_id)
    # Что не прошло сверку: видно в журнале, по этому списку правится инструкция агента.
    payload["verification"] = {"retried": retried, "first_attempt": first_problems[:8], "final": problems[:8]}
    usage = _usage(totals, started, llm)
    payload["steps"] = ctx.steps
    payload["usage"] = usage
    message = store.add_message(vehicle_id, ctx.session_id, "assistant", payload)
    store.finish_turn(turn_id, payload["kind"], usage["duration_ms"], ctx.diagnosed_this_turn)
    await emit({"type": "message", "message": message})
    await emit({"type": "done", "usage": usage})


def _usage(totals: dict, started: float, llm: LLM) -> dict:
    return {
        "input_tokens": totals["input_tokens"], "output_tokens": totals["output_tokens"],
        "cache_read_tokens": totals["cache_read_tokens"],
        "cost": round(totals["cost"], 5), "cost_rub": round(totals["cost_rub"], 2),
        "duration_ms": int((time.monotonic() - started) * 1000),
        "llm_calls": totals["llm_calls"], "model": llm.model, "mock": llm.is_mock,
    }


LIMITS = {"observations": 4, "hypotheses": 3, "checks": 6, "repair": 4, "limitations": 3, "conflicts": 3}


def _cap(answer: dict) -> None:
    """Ответ должен помещаться на экран телефона: длинные списки обрезаются до главного."""
    for key, limit in LIMITS.items():
        answer[key] = answer[key][:limit]


def _unsourced(ctx: TurnContext, answer: dict) -> bool:
    """F4: агент искал в руководствах, но в ответе нет ни одной подтверждённой ссылки и нет отказа.

    Такой ответ пересказывает найденное без страницы и цитаты. Механику он не показывается.
    """
    if not ctx.searched or answer["not_found"]:
        return False
    if ctx.draft or ctx.ticket or ctx.ticket_block or ctx.diagnosed_this_turn:
        return False
    return not (answer["checks"] or answer["repair"] or answer["conflicts"])


def _has_instruction(ctx: TurnContext, answer: dict) -> bool:
    """П9: среди ссылок есть страница, которая прямо относится к узлу неисправности."""
    code = (ctx.diagnosis or {}).get("anomaly_type")
    if not code:
        return False
    verifier = ctx.verifier()
    return any(
        rules.page_relevant(code, verifier.page(ref["manual_id"], ref["pdf_page"]) or "")
        for item in answer["checks"] + answer["repair"] for ref in item["refs"]
    )


def _apply_conflicts(ctx: TurnContext, answer: dict, question: str) -> None:
    """П18: к расхождениям, которые нашла модель, код добавляет подтверждённые из реестра и помечает спорные шаги."""
    if ctx.assessment and ctx.assessment["outcome"] in ("check_failed", "normal"):
        answer["conflicts"] = []
        return
    items = answer["checks"] + answer["repair"]
    registry = conflicts.from_registry(ctx.index, ctx.allowed_manuals, question, items)
    answer["conflicts"] = conflicts.merge(answer.get("conflicts") or [], registry)
    conflicts.mark_disputed(items, answer["conflicts"])
    if answer["conflicts"]:
        # Механик должен узнать о расхождении из первой же фразы, а не из блока ниже.
        if answer["not_found"] or not answer["summary"]:
            answer["summary"] = CONFLICT_LEAD
        elif not re.search(r"расхо[дж]|противореч|по-разному|разн\w+ (требован|услов|формулиров)", answer["summary"].lower()):
            answer["summary"] = f"{answer['summary'].rstrip()} {CONFLICT_LEAD}"
        answer["not_found"] = False


def _build_message(ctx: TurnContext, answer: dict, problems: list[str], confirmed_draft_id: str | None) -> dict:
    vehicle, engine = ctx.vehicle, ctx.vehicle["engine_model"]
    if problems:
        answer["limitations"].append(HIDDEN_NOTE)

    if ctx.ticket:
        return {"kind": "ticket_created", "text": f"Заявка {ctx.ticket['ticket_id']} создана в ТОиР.", "ticket": ctx.ticket}

    if confirmed_draft_id:
        failed = next((s for s in reversed(ctx.steps) if s["tool"] == "submit_ticket" and s["status"] == "error"), None)
        reason = failed["detail"] if failed else "Причина не определена."
        return {"kind": "notice", "text": f"Заявка не отправлена. {reason}"}

    if ctx.draft:
        return {"kind": "ticket_draft", "text": answer["summary"] or "Черновик заявки готов. Проверьте состав и подтвердите.",
                "draft": ctx.draft}

    if ctx.diagnosed_this_turn and ctx.diagnosis and ctx.assessment:
        assessment = json.loads(json.dumps(ctx.assessment))
        outcome = assessment["outcome"]
        payload = {"kind": "verdict", "diagnosis": ctx.diagnosis, "assessment": assessment}
        if outcome == "check_failed":
            # П5: при сбое записи текст задаёт код, выводы модели о двигателе не показываются.
            payload["text"] = ("Запись непригодна для анализа. Выводов о двигателе нет. "
                               "Повторите запись на холостом ходу и запросите результат снова.")
            return payload
        if outcome == "normal":
            payload["text"] = answer["summary"] or "Значимых отклонений не найдено, эксплуатацию можно продолжать."
            payload["answer"] = {**EMPTY_ANSWER, "summary": payload["text"], "observations": answer["observations"],
                                 "limitations": answer["limitations"]}
            return payload
        if assessment["flags"]["engine_mismatch"]:
            # П16: карточка машины важнее результата модели. Текст задаёт код: диагноза, гипотез и шагов
            # по этому типу нет, даже если модель их написала.
            payload["text"] = MISMATCH_TEXT
            payload["answer"] = {
                **EMPTY_ANSWER, "summary": MISMATCH_TEXT, "not_found": True,
                "limitations": [f"Нормативы и процедуры для типа «{ctx.diagnosis.get('anomaly_title')}» есть только "
                                "в руководствах других двигателей. Агент их не подставляет и тип на похожий не заменяет."],
                "recommendation_text": prompt.mismatch_text(vehicle, ctx.diagnosis),
            }
            return payload
        if ctx.kb_empty:
            # База знаний пуста: это не «инструкции нет», а не загруженные руководства. Говорим прямо.
            text = KB_EMPTY_TEXT.format(engine=engine)
            payload["text"] = f"Проверка показала отклонение: {ctx.diagnosis.get('anomaly_title')}. {text}"
            assessment["ticket_allowed"] = False
            assessment["ticket_block_reason"] = text
            payload["answer"] = {**EMPTY_ANSWER, "summary": payload["text"], "limitations": [text]}
            return payload
        payload["text"] = answer["summary"] or f"Проверка показала отклонение: {ctx.diagnosis.get('anomaly_title')}."
        reason = None
        if not _has_instruction(ctx, answer):
            # П10: применимой инструкции нет. Заявку не предлагаем, даём текст рекомендации на дефектовку.
            reason = (f"В руководстве на двигатель {engine} нет применимой инструкции по этой неисправности, "
                      "заявка в ТОиР не отправлена.")
            answer["not_found"] = not (answer["checks"] or answer["repair"])
            if assessment["ticket_allowed"]:
                assessment["ticket_allowed"] = False
                assessment["ticket_block_reason"] = (
                    f"В руководстве на двигатель {engine} не найдена инструкция по этой неисправности. "
                    "Рекомендуется дефектовка, заявка в ТОиР не отправляется."
                )
        if reason:
            answer["recommendation_text"] = prompt.recommendation_text(vehicle, ctx.diagnosis, reason)
        payload["answer"] = answer
        return payload

    if ctx.ticket_block:
        answer["summary"] = answer["summary"] or f"Заявку оформить нельзя. {ctx.ticket_block}"
        if ctx.no_instruction and ctx.diagnosis:
            answer["recommendation_text"] = prompt.recommendation_text(vehicle, ctx.diagnosis, ctx.ticket_block)
        return {"kind": "answer", "text": answer["summary"], "answer": answer}

    if ctx.kb_empty and (ctx.searched or ctx.ticket_block or answer["not_found"]):
        return {"kind": "notice", "text": KB_EMPTY_TEXT.format(engine=engine)}

    if _unsourced(ctx, answer):
        # Факт без страницы и цитаты не показываем: вместо пересказа честный отказ.
        answer.update(summary=UNSOURCED_TEXT, observations=[], not_found=True)

    has_body = any(
        answer[k] for k in ("observations", "hypotheses", "checks", "repair", "limitations", "conflicts")
    ) or answer["not_found"]
    if not has_body:
        return {"kind": "notice", "text": answer["summary"] or "Не удалось подготовить ответ. Повторите вопрос."}
    if not answer["summary"]:
        answer["summary"] = ("В руководствах на двигатель этой машины ответа нет." if answer["not_found"]
                             else "Ответ по руководству, смотрите пункты ниже.")
    return {"kind": "answer", "text": answer["summary"], "answer": answer}
