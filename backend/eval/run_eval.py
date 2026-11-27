"""Прогон контрольных вопросов по руководствам (КС3).

Жюри сверяет ответ агента с PDF: совпадает ли норматив, указана ли страница, нет ли выдуманных
цифр, отказывает ли агент на вопрос вне базы. Этот скрипт делает ту же сверку по нашему набору.

Три режима:
  python -m eval.run_eval data            # сверка самого набора: числа стоят на ожидаемых страницах
  python -m eval.run_eval search          # находит ли поиск нужную страницу по тексту вопроса (без модели)
  python -m eval.run_eval ask [--api URL] # ответы агента через работающий сервер (нужна настоящая модель)

В наборе нет текста руководств: только вопрос, документ, страница и ожидаемые числа.
Режим ask очищает чат по машинам из набора.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

QUESTIONS = Path(__file__).with_name("questions.json")


def service_headers() -> dict[str, str]:
    """Сервер с входом по PIN (AUTH_REQUIRED=1) пускает скрипт по ключу внешней системы из INTEGRATION_API_KEYS."""
    key = os.environ.get("INTEGRATION_API_KEY", "").strip()
    return {"X-API-Key": key} if key else {}


def norm(text: str) -> str:
    text = text.lower().replace("ё", "е").replace(",", ".")
    for dash in ("–", "—", "…", "..."):
        text = text.replace(dash, "-")
    return " ".join(text.split())


def has_numbers(text: str, variants: list[list[str]]) -> bool:
    """Достаточно одного варианта записи: в нём должны встретиться все числа."""
    flat = norm(text)
    return any(all(norm(n) in flat for n in variant) for variant in variants)


def load() -> list[dict]:
    return json.loads(QUESTIONS.read_text(encoding="utf-8"))


def engine_manuals(vehicle_id: str) -> list[str]:
    from app import fleet
    from app.manuals import manuals_for_engine

    return [m.id for m in manuals_for_engine(fleet.get_vehicle(vehicle_id)["engine_model"])]


def run_data() -> int:
    from app.kb.index import get_index

    index, bad = get_index(), 0
    for q in load():
        if not q.get("pages"):
            continue
        allowed = engine_manuals(q["vehicle_id"])
        text = " ".join(index.page_text(m, p) or "" for m, p in q["pages"])
        ok = all(m in allowed for m, _ in q["pages"]) and has_numbers(text, q["numbers"])
        bad += not ok
        print(f"{'ok  ' if ok else 'FAIL'} {q['id']}  {q['question']}")
    print(f"\nНабор: вопросов {len(load())}, расхождений с руководствами {bad}")
    return bad


def run_search() -> int:
    from app.kb.index import get_index

    index, missed, total = get_index(), 0, 0
    for q in load():
        if not q.get("pages"):
            continue
        total += 1
        hits = index.search(q["question"], engine_manuals(q["vehicle_id"]), limit=6, every_manual=True)
        found = [(h["manual_id"], h["pdf_page"]) for h in hits]
        expected = [tuple(p) for p in q["pages"]]
        rank = next((i + 1 for i, hit in enumerate(found) if hit in expected), None)
        missed += rank is None
        print(f"{'место ' + str(rank) if rank else 'НЕТ    '}  {q['id']}  {q['question']}")
    print(f"\nПоиск по тексту вопроса: нужная страница в выдаче у {total - missed} из {total}")
    return missed


def _texts(answer: dict) -> tuple[str, set[tuple[str, int]]]:
    parts, pages = [answer.get("summary") or ""], set()
    parts += answer.get("observations") or []
    for key in ("checks", "repair"):
        for item in answer.get(key) or []:
            parts.append(item["text"])
            for ref in item["refs"]:
                parts.append(ref["quote"])
                pages.add((ref["manual_id"], ref["pdf_page"]))
    for block in answer.get("conflicts") or []:
        for statement in block["statements"]:
            parts += [statement.get("text") or "", statement["ref"]["quote"]]
            pages.add((statement["ref"]["manual_id"], statement["ref"]["pdf_page"]))
    return " ".join(parts), pages


def run_ask(api: str, only: str | None) -> int:
    import httpx

    failed, rows, tokens_in, tokens_out, cost = 0, [], 0, 0, 0.0
    with httpx.Client(base_url=api, headers=service_headers(), timeout=600) as http:
        llm = http.get("/api/config").json().get("llm") or {}
        print(f"Модель: {llm.get('model')} ({llm.get('provider')})\n", flush=True)
        for q in load():
            if only and not q["id"].startswith(only):
                continue
            vehicle = http.get(f"/api/vehicles/{q['vehicle_id']}").json()
            # Каждый вопрос задаётся в чистом чате: прошлые ответы не должны подсказывать или сбивать.
            http.delete(f"/api/conversations/{q['vehicle_id']}")
            body = {"vehicle_id": q["vehicle_id"], "session_id": vehicle["sessions"][-1]["session_id"], "text": q["question"]}
            started, message, error = time.monotonic(), None, None
            with http.stream("POST", "/api/chat", json=body) as response:
                for line in response.iter_lines():
                    if not line.strip():
                        continue
                    event = json.loads(line)
                    if event["type"] == "message":
                        message = event["message"]
                    elif event["type"] == "error":
                        error = event["text"]
            seconds = time.monotonic() - started
            if message is None:
                failed += 1
                rows.append((q["id"], "ОШИБКА", error or "нет ответа", seconds))
                print(f"ОШИБКА {q['id']}: {error}")
                continue
            answer = message.get("answer") or {}
            text, pages = _texts(answer)
            usage = message.get("usage") or {}
            tokens_in += usage.get("input_tokens", 0)
            tokens_out += usage.get("output_tokens", 0)
            cost += usage.get("cost_rub", 0)
            problems = []
            if q.get("not_found"):
                # Отказ — это либо «ответа нет», либо прямое объяснение, что вопрос к этому двигателю не относится.
                # Объяснение может ссылаться на руководство этого же двигателя, но норматива чужого в нём быть не должно.
                declined = answer.get("not_found") or re.search(
                    r"\bнет\b|не относ|не примен|отсутств|не предусмотр|не использу", norm(message.get("text") or ""))
                if not declined:
                    problems.append("нет отказа")
                if any(norm(n) in norm(text) for n in q.get("forbidden", [])):
                    problems.append("норматив чужого двигателя")
            else:
                if not pages & {tuple(p) for p in q["pages"]}:
                    problems.append("нет ожидаемой страницы")
                if not has_numbers(text, q["numbers"]):
                    problems.append("нет ожидаемых чисел")
                if q.get("conflict") and not answer.get("conflicts"):
                    problems.append("расхождение не показано")
            failed += bool(problems)
            cited = ", ".join(f"{m} {p}" for m, p in sorted(pages)) or "нет ссылок"
            rows.append((q["id"], "ok" if not problems else "; ".join(problems), cited, seconds))
            print(f"{'ok  ' if not problems else 'FAIL'} {q['id']} {seconds:5.1f} с  {'; '.join(problems)}\n     {message.get('text', '')[:160]}\n     {cited}", flush=True)
    print(f"\nИтог: прошло {len(rows) - failed} из {len(rows)}. Токены: вход {tokens_in}, выход {tokens_out}. Стоимость: {cost:.2f} ₽")
    _save(llm, rows, failed, tokens_in, tokens_out, cost)
    return failed


def _save(llm: dict, rows: list, failed: int, tokens_in: int, tokens_out: int, cost: float) -> None:
    import re
    from datetime import datetime

    from app.config import get_settings

    folder = get_settings().data_dir / "eval"
    folder.mkdir(parents=True, exist_ok=True)
    name = re.sub(r"[^0-9A-Za-z._-]+", "-", str(llm.get("model") or "model"))
    lines = [f"# Контрольные вопросы: {llm.get('model')} ({llm.get('provider')})", "",
             f"Прошло {len(rows) - failed} из {len(rows)}. Токены: вход {tokens_in}, выход {tokens_out}. Стоимость: {cost:.2f} ₽.",
             "", "| Вопрос | Итог | Ссылки | Время, с |", "|---|---|---|---|"]
    lines += [f"| {r[0]} | {r[1]} | {r[2]} | {r[3]:.1f} |" for r in rows]
    path = folder / f"questions-{name}-{datetime.now():%Y%m%d-%H%M}.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Отчёт: {path}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("mode", choices=["data", "search", "ask"])
    parser.add_argument("--api", default="http://127.0.0.1:8000")
    parser.add_argument("--only", help="начало идентификатора вопроса, например 236 или neg")
    args = parser.parse_args()
    if args.mode == "data":
        return run_data()
    if args.mode == "search":
        return run_search()
    return run_ask(args.api, args.only)


if __name__ == "__main__":
    sys.exit(1 if main() else 0)
