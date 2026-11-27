"""Журнал для администратора: страницы с сервера, фильтры, разбор случаев, склейка повторов."""
from __future__ import annotations

import httpx
import pytest

from app import journal
from app.config import get_settings
from app.store import Store

REF = {"manual_id": "yamz236_rk", "short": "РК ЯМЗ-236М2", "pdf_page": 10, "designation": "", "quote": ""}
OK = {"kind": "answer", "text": "Давление масла не менее 400 кПа.",
      "answer": {"not_found": False, "checks": [{"text": "Проверить давление манометром", "refs": [REF]}]},
      "steps": [{"tool": "search_manuals"}], "usage": {"duration_ms": 4000, "input_tokens": 10, "output_tokens": 5}}
NONE = {"kind": "answer", "text": "В руководствах на двигатель этой машины ответа нет.", "answer": {"not_found": True}}


@pytest.fixture
def store(environment):
    return Store(get_settings().db_path)


def ask(store, vehicle_id, text, payload, author=None, at=None, session="S-1"):
    asked = {"text": text, **({"author": author} if author else {})}
    store.add_message(vehicle_id, session, "user", asked)
    message = store.add_message(vehicle_id, session, "assistant", payload)
    if at:
        store._exec("UPDATE messages SET created_at=? WHERE id=?", (at, int(message["id"][2:])))
    return message["id"]


def page(store, status="all", page_no=1, size=20, **filters):
    if "start" in filters or "end" in filters:
        lo, hi = journal.period(filters.pop("start", None), filters.pop("end", None))
        filters["from_ts"], filters["to_ts"] = (lo.timestamp() if lo else None), (hi.timestamp() if hi else None)
    return journal.page(store, filters, status, page_no, size)


def test_whole_journal_is_paged_on_server(store):
    for i in range(25):
        ask(store, "A101TT77" if i % 2 else "B202TT77", f"Вопрос номер {i}", OK, author="Иванов" if i < 10 else "Петров")
    first = page(store, size=10)
    assert first["total"] == 25 and first["page"] == 1 and first["page_size"] == 10 and len(first["items"]) == 10
    assert first["items"][0]["question"] == "Вопрос номер 24"  # новые сверху
    last = page(store, page_no=3, size=10)
    assert len(last["items"]) == 5 and last["items"][-1]["question"] == "Вопрос номер 0"
    assert page(store, page_no=9, size=10)["page"] == 3  # за концом — последняя страница
    item = first["items"][0]
    assert item["sources"] == [{"manual_id": "yamz236_rk", "short": "РК ЯМЗ-236М2", "pdf_page": 10}]
    assert item["tools"] == ["search_manuals"] and item["usage"]["duration_ms"] == 4000
    assert item["gap"] is None and item["status"] is None and item["vehicle_title"]


def test_filters_by_vehicle_mechanic_text_type_and_dates(store):
    ask(store, "A101TT77", "Какое давление МАСЛА?", OK, author="Иванов", at="2026-11-20T10:00:00+03:00")
    ask(store, "B202TT77", "Зазор клапанов", OK, author="Петров", at="2026-11-25T10:00:00+03:00")
    ask(store, "B202TT77", "Расход топлива у самолёта", NONE, author="Петров", at="2026-11-26T23:30:00+03:00")
    assert page(store, vehicle_id="B202TT77")["total"] == 2
    assert page(store, mechanic="иванов")["total"] == 1  # без учёта регистра
    assert [i["vehicle_id"] for i in page(store, q="какое ДАВЛЕНИЕ")["items"]] == ["A101TT77"]  # регистр по-русски
    assert page(store, q="400 кпа")["total"] == 2  # и по тексту ответа
    assert page(store, q="100%")["total"] == 0  # знаки поиска не работают как шаблон
    assert [i["question"] for i in page(store, type="no_answer")["items"]] == ["Расход топлива у самолёта"]
    assert page(store, start="2026-11-25", end="2026-11-26")["total"] == 2  # конец периода включительно
    assert page(store, start="2026-11-26")["total"] == 1
    assert page(store, end="2026-11-24")["total"] == 1
    assert page(store, start="2026-11-26T23:00", end="2026-11-26T23:59")["total"] == 1  # смена по часам
    with pytest.raises(ValueError):
        journal.period("вчера", None)
    facets = journal.facets(store)
    assert facets["mechanics"] == ["Иванов", "Петров"]
    assert [v["vehicle_id"] for v in facets["vehicles"]] == ["A101TT77", "B202TT77"]


def test_page_does_not_query_each_row(store):
    for i in range(30):
        ask(store, "A101TT77", f"Вопрос {i}", NONE if i % 3 else OK)
    store.add_report(2, "A101TT77", "Ответ неверный", "", "Петров")
    page(store)  # индекс журнала уже дописан
    statements: list[str] = []
    store._db.set_trace_callback(statements.append)
    page(store, size=5)
    few = len(statements)
    statements.clear()
    page(store, size=25)
    store._db.set_trace_callback(None)
    assert len(statements) == few <= 12  # число запросов не растёт с числом строк


def test_case_statuses_comment_reviewer_and_history(store):
    item = ask(store, "A101TT77", "Расход топлива у самолёта", NONE)
    assert page(store)["items"][0]["status"] == "new" and journal.open_count(store) == 1
    journal.set_status(store, [item], "in_work", "Спросили производителя", "Сидоров")
    row = page(store, status="open")["items"][0]
    assert row["status"] == "in_work" and row["gap"]["status_label"] == "В работе"
    assert journal.open_count(store) == 1 and page(store, status="in_work")["total"] == 1
    journal.set_status(store, [item], "reviewed", None, "Сидоров")
    assert journal.open_count(store) == 0 and page(store, status="open")["total"] == 0
    card = journal.case(store, item)
    assert card["status"] == "reviewed" and card["comment"] == "Спросили производителя"  # комментарий прежний
    assert card["reviewer"] == "Сидоров" and card["updated_at"]
    assert [(h["status"], h["comment"], h["reviewer"]) for h in card["history"]] == [
        ("in_work", "Спросили производителя", "Сидоров"), ("reviewed", "", "Сидоров")]
    with pytest.raises(ValueError):
        journal.set_status(store, [item], "closed")


def test_new_mechanic_message_reopens_reviewed_case(store):
    item = ask(store, "A101TT77", "Какое давление масла?", OK)
    store.add_report(int(item[2:]), "A101TT77", "Ответ неверный", "На стр. 19 другая цифра", "Петров")
    row = page(store)["items"][0]
    assert row["gap"]["type"] == "report" and row["report"]["author"] == "Петров" and row["status"] == "new"
    journal.set_status(store, [item], "reviewed")
    assert journal.open_count(store) == 0
    store.add_report(int(item[2:]), "A101TT77", "Ответ неверный", "Опять не то", "Козлов")
    row = page(store)["items"][0]
    # Повторное сообщение на тот же ответ — та же строка, повторилось 2 раза, снова в работе
    assert row["status"] == "new" and row["repeats"] == 2 and row["reports_count"] == 2
    assert row["report"]["author"] == "Козлов" and page(store)["total"] == 1
    assert len(journal.case(store, item)["reports"]) == 2


def test_repeated_unanswered_questions_are_one_row(store):
    # B202TT77 и C303TT77 — один двигатель ЗМЗ-5234.10, A101TT77 — другой
    first = ask(store, "B202TT77", "Какой момент затяжки ГБЦ?", NONE, author="Иванов")
    ask(store, "C303TT77", "  какой МОМЕНТ затяжки   гбц ", NONE, author="Петров")
    ask(store, "A101TT77", "Какой момент затяжки ГБЦ?", NONE)
    ask(store, "B202TT77", "Какое давление масла?", OK)
    rows = page(store)["items"]
    assert page(store)["total"] == 3
    group = next(r for r in rows if r["vehicle_id"] == "C303TT77")
    assert group["repeats"] == 2 and group["gap"]["type"] == "no_answer"
    assert next(r for r in rows if r["vehicle_id"] == "A101TT77")["repeats"] == 1
    # «Требуют внимания» и число в шапке считают группы
    assert page(store, status="open")["total"] == 2 and journal.open_count(store) == 2
    card = journal.case(store, first)
    assert [o["vehicle_id"] for o in card["occurrences"]] == ["C303TT77", "B202TT77"] and card["repeats"] == 2
    # Разбор отмечает всю группу
    assert journal.set_status(store, [group["id"]], "reviewed", "Добавили в базу знаний", "Сидоров")["updated"] == 2
    assert journal.open_count(store) == 1 and journal.case(store, first)["status"] == "reviewed"
    # Новый повтор после разбора возвращает группу в работу
    ask(store, "B202TT77", "Какой момент затяжки ГБЦ", NONE)
    row = next(r for r in page(store, status="open")["items"] if r["engine_model"] == "ЗМЗ-5234.10")
    assert row["repeats"] == 3 and row["status"] == "new"
    # Фильтр по машине сужает группу
    assert page(store, vehicle_id="C303TT77")["items"][0]["repeats"] == 1


def test_several_rows_are_marked_at_once(store):
    a = ask(store, "A101TT77", "Вопрос без ответа один", NONE)
    b = ask(store, "B202TT77", "Вопрос без ответа два", NONE)
    assert journal.set_status(store, [a, b], "in_work", reviewer="Сидоров")["updated"] == 2
    assert page(store, status="in_work")["total"] == 2


def test_old_reviews_are_moved_to_statuses(store):
    item = ask(store, "A101TT77", "Расход топлива у самолёта", NONE)
    store._exec("INSERT INTO reviews (message_id, reviewed_at) VALUES (?, ?)", (int(item[2:]), "2026-11-26T10:00:00+03:00"))
    store._exec("DELETE FROM journal_meta WHERE key='reviews_moved'")
    journal.init(store)
    card = journal.case(store, item)
    assert card["status"] == "reviewed" and card["updated_at"] == "2026-11-26T10:00:00+03:00"
    assert card["history"][0]["status"] == "reviewed"
    # Старый вид журнала и старые вызовы видят то же
    assert store.audit()[0]["gap"]["reviewed_at"] == "2026-11-26T10:00:00+03:00" and store.open_gaps() == 0


def test_cleared_chat_leaves_the_journal(store):
    ask(store, "A101TT77", "Вопрос", OK)
    ask(store, "B202TT77", "Вопрос", OK)
    assert page(store)["total"] == 2
    store.clear_messages("A101TT77")
    assert page(store)["total"] == 1


# --- эндпоинты ---
@pytest.fixture
async def client(store):
    from app import main

    main.state["store"] = store
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://test") as c:
        yield c
    main.state.pop("store", None)


async def test_audit_endpoint_pages_filters_and_marks(client, store):
    for i in range(7):
        ask(store, "A101TT77", f"Вопрос без ответа {i}", NONE, author="Иванов")
    ask(store, "B202TT77", "Давление масла", OK, author="Петров")
    r = await client.get("/api/audit", params={"page": 2, "page_size": 3, "mechanic": "Иванов"})
    data = r.json()
    assert r.status_code == 200 and data["total"] == 7 and data["page"] == 2 and len(data["items"]) == 3
    assert data["gaps_open"] == 7 and "Петров" in data["facets"]["mechanics"]
    assert (await client.get("/api/audit", params={"limit": 2})).json()["page_size"] == 2  # старый параметр
    assert (await client.get("/api/audit", params={"type": "что-то"})).status_code == 400
    assert (await client.get("/api/audit", params={"from": "вчера"})).status_code == 400
    assert (await client.get("/api/audit", params={"status": "closed"})).status_code == 422
    ids = [i["id"] for i in data["items"]]
    r = await client.post("/api/audit/status", json={"ids": ids, "status": "reviewed", "comment": "Ок", "reviewer": "Сидоров"})
    assert r.status_code == 200 and r.json()["updated"] == 3 and r.json()["gaps_open"] == 4
    assert (await client.get("/api/audit/gaps")).json() == {"open": 4}
    card = (await client.get(f"/api/audit/{ids[0]}")).json()
    assert card["status"] == "reviewed" and card["comment"] == "Ок" and card["history"][0]["reviewer"] == "Сидоров"
    assert (await client.get("/api/audit/m_999")).status_code == 404
    assert (await client.post("/api/audit/status", json={"ids": ["m_999"], "status": "new"})).status_code == 404
    # Старая отметка «Разобрано» работает поверх статусов
    r = await client.post(f"/api/audit/{ids[0]}/review", json={"reviewed": False})
    assert r.json()["reviewed_at"] is None and (await client.get("/api/audit/gaps")).json() == {"open": 5}
