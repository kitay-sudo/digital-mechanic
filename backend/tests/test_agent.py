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
    assert message["assessment"]["flags"]["engine_mismatch"] and not message["assessment"]["ticket_allowed"]
    assert message["answer"]["recommendation_text"]


async def test_question_outside_knowledge_base_is_declined(store, index, services):  # С2, F4
    message, _ = await turn(store, index, "T792HO98", "S-0043", "Какой расход топлива у самолёта на взлёте?")
    assert message["kind"] == "answer" and message["answer"]["not_found"]
