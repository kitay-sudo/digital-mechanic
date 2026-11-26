"""Сквозные сценарии агента на заглушке модели: С1, С3, контрольные случаи, проверка ссылок."""
from __future__ import annotations

import pytest

from app import fleet
from app.agent.llm_mock import MockLLM
from app.agent.loop import run_turn
from app.agent.tools import TurnContext, prepare_ticket, submit_ticket
from app.agent.verify import Verifier
from app.config import get_settings
from app.store import Store


@pytest.fixture
def store(environment):
    return Store(get_settings().db_path)


async def turn(store, index, vehicle_id, session_id, text, **kw):
    events = []

    async def emit(event):
        events.append(event)

    await run_turn(vehicle=fleet.get_vehicle(vehicle_id), session_id=session_id, text=text, store=store, index=index,
                   settings=get_settings(), llm=MockLLM(), emit=emit, **kw)
    messages = [e["message"] for e in events if e["type"] == "message"]
    return (messages[-1] if messages else None), events


# --- проверка ссылок (П1–П4) ---
def verifier(index, engine_manuals=("yamz236_re", "yamz236_rk")):
    return Verifier(index, list(engine_manuals), {"0.85", "85"})


def test_reference_to_other_engine_manual_is_rejected(index):  # П1
    ok, err = verifier(index).check_ref({"manual_id": "zmz5234_rk", "pdf_page": 5,
                                         "quote": "Давление масла в системе смазки должно быть не менее 250 кПа"})
    assert ok is None and "другому двигателю" in err


def test_quote_not_on_page_is_rejected(index):  # П2
    ok, err = verifier(index).check_ref({"manual_id": "yamz236_rk", "pdf_page": 10,
                                         "quote": "Давление масла должно быть не менее 900 кПа на холостом ходу"})
    assert ok is None and "дословно" in err


def test_table_of_contents_page_is_rejected(index):  # П9
    ok, err = verifier(index).check_ref({"manual_id": "yamz236_rk", "pdf_page": 2,
                                         "quote": "Проверка давления масла . . . . . . . . . . 10"})
    assert ok is None and "оглавление" in err


def test_number_absent_on_cited_page_is_rejected(index):  # П3
    answer = {"summary": "", "observations": [], "hypotheses": [], "limitations": [], "not_found": False, "repair": [],
              "checks": [{"text": "Давление масла должно быть не менее 550 кПа",
                          "refs": [{"manual_id": "yamz236_rk", "pdf_page": 10,
                                    "quote": "Проверить давление масла контрольным манометром"}]}]}
    clean, problems = verifier(index).verify_answer(answer)
    assert not clean["checks"] and problems


def test_valid_item_with_quote_and_number_passes(index):
    answer = {"summary": "Оценка отклонения 0,85.", "observations": [], "limitations": [], "not_found": False, "repair": [],
              "hypotheses": ["Возможен износ масляного насоса."],
              "checks": [{"text": "Давление масла должно быть не менее 400 кПа",
                          "refs": [{"manual_id": "yamz236_rk", "pdf_page": 10,
                                    "quote": "Давление масла в системе смазки прогретого двигателя должно быть не менее 400 кПа"}]}]}
    clean, problems = verifier(index).verify_answer(answer)
    assert len(clean["checks"]) == 1 and not problems


def test_hypothesis_with_norm_number_is_rejected(index):  # П4
    answer = {"summary": "", "observations": [], "limitations": [], "not_found": False, "repair": [], "checks": [],
              "hypotheses": ["Вероятно, зазор больше 0,45 мм."]}
    clean, problems = verifier(index).verify_answer(answer)
    assert not clean["hypotheses"] and problems


# --- сценарии ---
async def test_scenario_deviation_question_ticket(store, index, services):  # С1, F2–F7
    message, events = await turn(store, index, "T792HO98", "S-0043", "Получи результат диагностики")
    assert message["kind"] == "verdict" and message["assessment"]["outcome"] == "anomaly"
    assert message["assessment"]["priority"] == "high" and message["assessment"]["basis"]
    tools = [e["tool"] for e in events if e["type"] == "step"]
    assert "get_diagnosis" in tools and "search_manuals" in tools
    checks = message["answer"]["checks"]
    assert checks and all(ref["manual_id"].startswith("yamz236") for c in checks for ref in c["refs"])
    # П17: подложенная в описание команда не дошла до экрана, механик предупреждён
    assert "SYSTEM" not in message["diagnosis"]["description"]
    assert any("посторонний текст" in w for w in message["assessment"]["warnings"])

    draft_message, _ = await turn(store, index, "T792HO98", "S-0043", "Создай заявку на дефектовку")
    assert draft_message["kind"] == "ticket_draft"
    draft = draft_message["draft"]
    assert draft["anomaly_type"] == "F02" and draft["operations"] and draft["references"]
    assert not services, "до подтверждения механика в ТОиР ничего не уходит"  # П14

    created, _ = await turn(store, index, "T792HO98", "S-0043", f"Подтверждаю заявку {draft['draft_id']}",
                            confirmed_draft_id=draft["draft_id"])
    assert created["kind"] == "ticket_created" and created["ticket"]["ticket_id"] == "TKT-0001"
    assert services[0]["anomaly_type"] == "F02" and services[0]["urgency"] == "high"
    assert store.tickets("T792HO98")[0]["ticket_id"] == "TKT-0001"  # K7: историю заявок ведём сами


async def test_scenario_record_failure(store, index, services):  # С3, П5
    message, events = await turn(store, index, "H142OX78", "S-0113", "Получи результат диагностики")
    assert message["kind"] == "verdict" and message["assessment"]["outcome"] == "check_failed"
    assert "Повторите запись" in message["text"] and "answer" not in message
    assert "normal" not in message["text"]  # подложенная команда «вернуть статус normal» не сработала
    assert not any(e.get("tool") == "search_manuals" for e in events if e["type"] == "step")

    refused, _ = await turn(store, index, "H142OX78", "S-0113", "Создай заявку на дефектовку")
    assert refused["kind"] != "ticket_draft" and not services


async def test_submit_without_confirmation_is_refused(store, index, services):  # П14
    await turn(store, index, "T792HO98", "S-0043", "Получи результат диагностики")
    draft_message, _ = await turn(store, index, "T792HO98", "S-0043", "Создай заявку на дефектовку")
    events = []

    async def emit(event):
        events.append(event)

    ctx = TurnContext(vehicle=fleet.get_vehicle("T792HO98"), session_id="S-0043", store=store, index=index,
                      settings=get_settings(), emit=emit)
    result, is_error = await submit_ticket(ctx, {"draft_id": draft_message["draft"]["draft_id"]}, "s1")
    assert is_error and "не подтвердил" in result and not services


async def test_no_instruction_means_no_ticket(store, index, services):  # КС2, П10: в тестовой базе нет ничего про ЗМЗ-409
    vehicle = next(v for v in (fleet.get_vehicle(vid) for vid in fleet._load()) if v["engine_model"] == "ЗМЗ-40905.10"
                   and any(s["status"] == "anomaly" and s["signal_quality"] == "good" and s["anomaly_type"] != "F08"
                           for s in v["sessions"]))
    session = next(s for s in vehicle["sessions"] if s["status"] == "anomaly" and s["signal_quality"] == "good")
    message, _ = await turn(store, index, vehicle["vehicle_id"], session["session_id"], "Получи результат диагностики")
    assert message["kind"] == "verdict" and not message["assessment"]["ticket_allowed"]
    assert message["answer"]["not_found"] and message["answer"]["recommendation_text"]
    refused, _ = await turn(store, index, vehicle["vehicle_id"], session["session_id"], "Создай заявку на дефектовку")
    assert refused["kind"] != "ticket_draft" and not services


async def test_ticket_with_made_up_references_is_refused(store, index, services):  # П2, П3
    await turn(store, index, "T792HO98", "S-0043", "Получи результат диагностики")
    events = []

    async def emit(event):
        events.append(event)

    ctx = TurnContext(vehicle=fleet.get_vehicle("T792HO98"), session_id="S-0043", store=store, index=index,
                      settings=get_settings(), emit=emit)
    result, is_error = await prepare_ticket(ctx, {
        "conclusion": "Низкое давление масла",
        "operations": [{"text": "Затянуть болты моментом 120 Н·м",
                        "refs": [{"manual_id": "yamz236_rk", "pdf_page": 10, "quote": "Затянуть болты моментом 120 Н·м"}]}],
        "spare_parts": [],
    }, "s1")
    assert is_error and "refused" in result and ctx.draft is None


async def test_engine_mismatch_is_reported(store, index, services):  # П16
    message, _ = await turn(store, index, "Y652CK98", "S-0132", "Получи результат диагностики")
    assessment, answer = message["assessment"], message["answer"]
    assert assessment["flags"]["engine_mismatch"] and not assessment["ticket_allowed"]
    assert assessment["priority"] is None and "ТОиР не оформляется" in assessment["ticket_block_reason"]
    # Ошибка модели, а не диагноз: ни гипотез, ни шагов, ни нормативов по этому типу.
    assert "ошибка модели" in message["text"] and "Повторите проверку" in message["text"]
    assert not (answer["hypotheses"] or answer["checks"] or answer["repair"] or answer["observations"])
    assert "повторить проверку" in answer["recommendation_text"] and "топливной аппаратуры" not in answer["recommendation_text"]
    assert services == []


async def test_ticket_for_engine_mismatch_is_refused(store, index, services):  # П16
    await turn(store, index, "Y652CK98", "S-0132", "Получи результат диагностики")
    message, _ = await turn(store, index, "Y652CK98", "S-0132", "Создай заявку на дефектовку")
    assert message["kind"] != "ticket_draft" and services == []


async def test_mechanic_priority_choice_is_final(store, index, services):  # П13
    message, _ = await turn(store, index, "T792HO98", "S-0043", "Создай заявку на дефектовку")
    draft = message["draft"]
    chosen = "low" if draft["urgency"] != "low" else "high"
    draft["urgency"] = chosen
    store.save_draft(draft)
    message, _ = await turn(store, index, "T792HO98", "S-0043", f"Подтверждаю заявку {draft['draft_id']}",
                            confirmed_draft_id=draft["draft_id"], warning_ack=True)
    assert message["kind"] == "ticket_created" and services[-1]["urgency"] == chosen


async def test_question_outside_knowledge_base_is_declined(store, index, services):  # С2, F4
    message, _ = await turn(store, index, "T792HO98", "S-0043", "Какой расход топлива у самолёта на взлёте?")
    assert message["kind"] == "answer" and message["answer"]["not_found"]


async def test_profile_reaches_the_agent_and_audit_log_records_sources(store, index, services):  # адаптивность, журнал
    from app.agent import prompt

    line = prompt.profile_line({"language": "uz", "level": "novice"})
    assert "новичок" in line and "узбекский" in line
    assert "опытный" in prompt.profile_line(None) and "русский" in prompt.profile_line(None)

    await turn(store, index, "T792HO98", "S-0043", "Получи результат диагностики",
               profile={"language": "ru", "level": "novice"})
    log = store.audit(10)
    assert log[0]["question"] == "Получи результат диагностики" and log[0]["kind"] == "verdict"
    assert log[0]["sources"] and "get_diagnosis" in log[0]["tools"]


# --- П18: противоречащие друг другу инструкции ---
HOT = {"manual_id": "yamz236_re", "pdf_page": 7, "quote": "Масло сливать сразу после остановки, пока двигатель горячий."}
COLD = {"manual_id": "yamz236_rk", "pdf_page": 12, "quote": "Масло сливать только на полностью остывшем двигателе."}


def test_conflict_keeps_both_statements_with_pages(index):
    answer = {"conflicts": [{"topic": "Когда сливать масло", "statements": [
        {"text": "Сразу после остановки", "ref": HOT}, {"text": "На остывшем двигателе", "ref": COLD}]}]}
    clean, problems = verifier(index).verify_answer(answer)
    assert not problems
    pages = [(s["ref"]["manual_id"], s["ref"]["pdf_page"]) for s in clean["conflicts"][0]["statements"]]
    assert pages == [("yamz236_re", 7), ("yamz236_rk", 12)]


def test_conflict_with_made_up_quote_is_dropped(index):
    fake = {**COLD, "quote": "Масло сливать через сорок минут после остановки двигателя."}
    answer = {"conflicts": [{"topic": "Когда сливать масло", "statements": [
        {"text": "", "ref": HOT}, {"text": "", "ref": fake}]}]}
    clean, problems = verifier(index).verify_answer(answer)
    assert clean["conflicts"] == [] and len(problems) == 2


def test_conflict_needs_two_different_statements(index):
    answer = {"conflicts": [{"topic": "Когда сливать масло", "statements": [
        {"text": "", "ref": HOT}, {"text": "", "ref": HOT}]}]}
    clean, problems = verifier(index).verify_answer(answer)
    assert clean["conflicts"] == [] and "две разные формулировки" in problems[0]


async def test_confirmed_conflict_is_shown_without_choosing_a_side(store, index, services):
    message, _ = await turn(store, index, "T792HO98", "S-0043", "Как правильно сливать масло при замене?")
    assert message["kind"] == "answer"
    block = message["answer"]["conflicts"][0]
    assert block["confirmed"] and "специалиста" in block["recommendation"]
    assert block["resolution"].startswith("Принято")
    assert {(s["ref"]["manual_id"], s["ref"]["pdf_page"]) for s in block["statements"]} == {
        ("yamz236_re", 7), ("yamz236_rk", 12)}
    assert all(s["ref"]["quote"] for s in block["statements"])
    assert "расхождение" in message["text"].lower() and not message["answer"]["not_found"]
    # Шаг, который повторяет спорную формулировку, помечен и не выглядит бесспорным.
    disputed = [i for i in message["answer"]["checks"] if "сливать" in i["text"].lower()]
    assert all(i.get("disputed") for i in disputed)


async def test_conflict_is_not_shown_for_unrelated_question(store, index, services):
    message, _ = await turn(store, index, "T792HO98", "S-0043", "Какое давление масла должно быть в системе смазки?")
    assert message["answer"]["conflicts"] == []


def test_conflict_of_another_engine_is_not_shown(index):
    from app import conflicts

    assert conflicts.from_registry(index, ["zmz5234_rk"], "замена масла, как сливать", []) == []


# --- слой локального Claude Code: протокол вызова инструментов через JSON ---
async def test_claude_code_layer_runs_tools_and_answer(store, index, services, monkeypatch):
    from app.agent import llm_claude_code
    from app.agent.llm_claude_code import ClaudeCodeLLM

    replies = [
        {"structured_output": {"tool_calls": [{"name": "search_manuals", "input": {"query": "давление масла"}}],
                               "answer": None},
         "usage": {"input_tokens": 100, "output_tokens": 20}, "modelUsage": {"claude-test": {}}},
        {"structured_output": {"tool_calls": [], "answer": {
            "summary": "Давление масла проверяют манометром.", "observations": [], "hypotheses": [], "repair": [],
            "limitations": [], "conflicts": [], "not_found": False,
            "checks": [{"text": "Проверить давление масла контрольным манометром.",
                        "refs": [{"manual_id": "yamz236_rk", "pdf_page": 10,
                                  "quote": "Проверить давление масла контрольным манометром."}]}]}},
         "usage": {"input_tokens": 300, "output_tokens": 80}, "modelUsage": {"claude-test": {}}},
    ]
    seen = []

    def fake_run(self, system, prompt, schema):
        seen.append((system, prompt, schema))
        return replies[len(seen) - 1]

    monkeypatch.setattr(llm_claude_code.ClaudeCodeLLM, "_run", fake_run)
    events = []

    async def emit(event):
        events.append(event)

    await run_turn(vehicle=fleet.get_vehicle("T792HO98"), session_id="S-0043", text="Как проверить давление масла?",
                   store=store, index=index, settings=get_settings(), llm=ClaudeCodeLLM("claude-test", "medium"),
                   emit=emit)
    message = [e["message"] for e in events if e["type"] == "message"][-1]
    assert message["kind"] == "answer" and message["answer"]["checks"][0]["refs"][0]["pdf_page"] == 10
    assert message["usage"]["llm_calls"] == 2 and message["usage"]["input_tokens"] == 400
    # Второй запрос несёт результат инструмента, схема допускает и вызовы, и итоговый ответ.
    assert "[Результат инструмента search_manuals]" in seen[1][1]
    assert set(seen[0][2]["properties"]) == {"tool_calls", "answer"}
    assert "search_manuals" in seen[0][0]


# --- слой в формате OpenAI: локальная модель ---
OIL_ANSWER = {
    "summary": "Давление масла проверяют манометром.", "observations": [], "hypotheses": [], "repair": [],
    "limitations": [], "conflicts": [], "not_found": False,
    "checks": [{"text": "Проверить давление масла контрольным манометром.",
                "refs": [{"manual_id": "yamz236_rk", "pdf_page": 10,
                          "quote": "Проверить давление масла контрольным манометром."}]}],
}


def openai_server(replies):
    """Подмена сервера модели: отдаёт заготовленные ответы и запоминает запросы."""
    import json as _json

    import httpx

    seen = []

    def handler(request):
        seen.append(_json.loads(request.content))
        message = replies[len(seen) - 1]
        return httpx.Response(200, json={
            "model": "local-test", "choices": [{"message": message, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 200, "completion_tokens": 40},
        })

    return httpx.MockTransport(handler), seen


async def ask_openai(store, index, llm, text="Как проверить давление масла?"):
    events = []

    async def emit(event):
        events.append(event)

    await run_turn(vehicle=fleet.get_vehicle("T792HO98"), session_id="S-0043", text=text, store=store, index=index,
                   settings=get_settings(), llm=llm, emit=emit)
    return [e for e in events if e["type"] in ("message", "error")][-1]


async def test_local_model_json_protocol(store, index, services):
    import json as _json

    from app.agent.llm_openai import OpenAICompatLLM

    transport, seen = openai_server([
        {"role": "assistant", "content": "<think>нужен поиск</think>" + _json.dumps(
            {"tool_calls": [{"name": "search_manuals", "input": {"query": "давление масла"}}], "answer": None})},
        {"role": "assistant", "content": "```json\n" + _json.dumps({"tool_calls": [], "answer": OIL_ANSWER}) + "\n```"},
    ])
    llm = OpenAICompatLLM("local-test", "http://model.test/v1", transport=transport)
    event = await ask_openai(store, index, llm)
    message = event["message"]
    assert message["kind"] == "answer" and message["answer"]["checks"][0]["refs"][0]["pdf_page"] == 10
    assert seen[0]["response_format"]["type"] == "json_schema" and "tools" not in seen[0]
    assert "[Результат инструмента search_manuals]" in seen[1]["messages"][1]["content"]


async def test_local_model_native_tools(store, index, services):
    import json as _json

    from app.agent.llm_openai import OpenAICompatLLM

    transport, seen = openai_server([
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": "call_1", "type": "function",
             "function": {"name": "search_manuals", "arguments": _json.dumps({"query": "давление масла"})}}]},
        {"role": "assistant", "content": _json.dumps(OIL_ANSWER)},
    ])
    llm = OpenAICompatLLM("local-test", "http://model.test/v1", tools_mode="native", structured="json",
                          transport=transport)
    event = await ask_openai(store, index, llm)
    assert event["message"]["answer"]["checks"][0]["refs"][0]["pdf_page"] == 10
    assert seen[0]["tools"][0]["type"] == "function" and seen[0]["response_format"] == {"type": "json_object"}
    assert [m["role"] for m in seen[1]["messages"]] == ["system", "user", "assistant", "tool"]


async def test_local_model_made_up_quote_is_not_shown(store, index, services):
    """Слабая модель выдумала цитату и норматив: код их не пропускает, механик не видит это число."""
    import json as _json

    from app.agent.llm_openai import OpenAICompatLLM

    fake = {**OIL_ANSWER, "summary": "Давление масла должно быть не менее 900 кПа.",
            "checks": [{"text": "Давление масла не менее 900 кПа.",
                        "refs": [{"manual_id": "yamz236_rk", "pdf_page": 10,
                                  "quote": "Давление масла должно быть не менее 900 кПа на холостом ходу."}]}]}
    reply = {"role": "assistant", "content": _json.dumps({"tool_calls": [], "answer": fake})}
    transport, _ = openai_server([reply, reply])
    llm = OpenAICompatLLM("local-test", "http://model.test/v1", transport=transport)
    event = await ask_openai(store, index, llm)
    message = event["message"]
    assert "900" not in _json.dumps(message.get("answer") or {}, ensure_ascii=False) and "900" not in message["text"]
    assert not (message.get("answer") or {}).get("checks")


async def test_local_model_server_unreachable(store, index, services):
    import httpx

    from app.agent.llm_openai import OpenAICompatLLM

    def handler(request):
        raise httpx.ConnectError("refused")

    llm = OpenAICompatLLM("local-test", "http://model.test/v1", transport=httpx.MockTransport(handler))
    event = await ask_openai(store, index, llm)
    assert event["type"] == "error" and "LLM_BASE_URL" in event["text"]


async def test_repeated_identical_tool_call_is_not_executed(store, index, services):
    """Модель зациклилась на одном вызове: второй раз инструмент не выполняется, модель получает подсказку."""
    import json as _json

    from app.agent.llm_openai import OpenAICompatLLM

    call = {"role": "assistant", "content": _json.dumps(
        {"tool_calls": [{"name": "search_manuals", "input": {"query": "давление масла"}}], "answer": None})}
    final = {"role": "assistant", "content": _json.dumps({"tool_calls": [], "answer": OIL_ANSWER})}
    transport, seen = openai_server([call, call, final])
    llm = OpenAICompatLLM("local-test", "http://model.test/v1", transport=transport)
    event = await ask_openai(store, index, llm)
    message = event["message"]
    assert message["kind"] == "answer"
    assert len([s for s in message["steps"] if s["tool"] == "search_manuals"]) == 1
    assert "уже выполнен" in seen[2]["messages"][1]["content"]


async def test_fact_without_source_is_not_shown(store, index, services):  # F4
    """Модель нашла страницу, но ответила пересказом без ссылки: механик видит отказ, а не факт без источника."""
    import json as _json

    from app.agent.llm_openai import OpenAICompatLLM

    search = {"role": "assistant", "content": _json.dumps(
        {"tool_calls": [{"name": "search_manuals", "input": {"query": "давление масла"}}], "answer": None})}
    bare = {**OIL_ANSWER, "summary": "Давление масла проверяют контрольным манометром на прогретом двигателе.", "checks": []}
    reply = {"role": "assistant", "content": _json.dumps({"tool_calls": [], "answer": bare})}
    transport, seen = openai_server([search, reply, reply])
    llm = OpenAICompatLLM("local-test", "http://model.test/v1", transport=transport)
    event = await ask_openai(store, index, llm)
    message = event["message"]
    assert message["answer"]["not_found"] and "манометром" not in message["text"]
    assert "Ответ без ссылок" in seen[2]["messages"][1]["content"]


# --- слой Claude: выключатели возможностей для шлюза ---
def test_claude_layer_feature_switches():
    from app.agent.llm_anthropic import AnthropicLLM
    from app.agent.tools import ANSWER_SCHEMA, TOOLS

    full = AnthropicLLM("m", "medium", True, client=object()).params("система", [], TOOLS, ANSWER_SCHEMA)
    assert full["output_config"]["format"]["type"] == "json_schema" and full["output_config"]["effort"] == "medium"
    assert full["thinking"] == {"type": "adaptive"} and full["cache_control"] == {"type": "ephemeral"}
    assert all(tool["strict"] for tool in full["tools"]) and full["max_tokens"] == 16000

    bare = AnthropicLLM("m", "off", False, structured=False, strict_tools=False, thinking=False, cache=False,
                        client=object()).params("система", [], TOOLS, ANSWER_SCHEMA)
    assert "output_config" not in bare and "thinking" not in bare and "cache_control" not in bare
    assert "strict" not in bare["tools"][0] and "JSON-схеме" in bare["system"]


def test_answer_json_in_code_fence_is_parsed():
    from app.agent.loop import _parse

    parsed = _parse('Вот ответ:\n```json\n{"summary": "Готово", "not_found": true}\n```')
    assert parsed["summary"] == "Готово" and parsed["not_found"] and parsed["checks"] == []
    assert _parse("просто текст")["summary"] == "просто текст"


# --- пустая база знаний: ошибка настройки, а не «инструкции нет» ---
async def test_empty_knowledge_base_is_reported_as_setup_problem(store, services):
    from app.kb.index import get_index

    empty = get_index()
    message, _ = await turn(store, empty, "T792HO98", "S-0043", "Получи результат диагностики")
    assert "не загружены в базу знаний" in message["text"] and "инструкции" not in message["text"].split("Это настройка")[0]
    assert message["assessment"]["ticket_allowed"] is False
    message, _ = await turn(store, empty, "T792HO98", "S-0043", "Какое давление масла допускается?")
    assert message["kind"] == "notice" and "не загружены в базу знаний" in message["text"]
