"""Заглушка модели для работы без ключа.

Нужна, чтобы весь путь (инструменты, правила, проверки, интерфейс) запускался и
тестировался без доступа к настоящей модели. Инструменты она выбирает по простым
признакам в тексте механика, а ответ собирает из найденных фрагментов дословно.
Качество ответов такой заглушки ниже, чем у настоящей модели: для демо и оценки
нужен ключ (LLM_PROVIDER=anthropic).
"""
from __future__ import annotations

import json
import re
import uuid

from .. import rules
from ..kb.text import split_sentences, tokens
from .llm import LLMResponse, ToolCall, text_of

CHECK_MARK = re.compile(
    r"провер|регулир|измер|замер|зазор|момент|давлен|должн|не более|не менее|снять|снима|затян|затяж|установ|осмотр|контрол|допуск"
)
REPAIR_MARK = re.compile(r"замен|ремонт|притир|шлиф|восстанов|устран|браку")
MOCK_NOTE = "Ответ собран заглушкой модели из найденных фрагментов дословно. Решение принимает механик."


def _blocks(content) -> list[dict]:
    return content if isinstance(content, list) else []


class MockLLM:
    name = "mock"
    model = "mock-llm"
    is_mock = True

    async def complete(self, system: str, messages: list[dict], tools: list[dict], schema: dict) -> LLMResponse:
        start = max(
            i for i, m in enumerate(messages)
            if m["role"] == "user" and "[Сообщение механика]" in text_of(m["content"])
        )
        context = text_of(messages[start]["content"])  # фото заглушка модели не смотрит
        user_text = context.split("[Сообщение механика]")[-1].strip()

        calls: dict[str, dict] = {}
        results: dict[str, list[dict]] = {}
        for message in messages[start + 1:]:
            for block in _blocks(message["content"]):
                if block.get("type") == "tool_use":
                    calls[block["id"]] = block
                elif block.get("type") == "tool_result":
                    call = calls.get(block["tool_use_id"])
                    if call:
                        try:
                            data = json.loads(block["content"])
                        except (TypeError, ValueError):
                            data = {}
                        results.setdefault(call["name"], []).append(data)

        saved = self._saved(context)
        session = re.search(r"Выбрана проверка (\S+?)[ .]", context)
        session_id = session.group(1) if session else ""
        novice = "уровень «новичок»" in context
        decision = self._decide(user_text, session_id, saved, results, novice)

        size_in = sum(len(json.dumps(m["content"], ensure_ascii=False, default=str)) for m in messages) + len(system)
        if isinstance(decision, list):
            content = [{"type": "tool_use", "id": c.id, "name": c.name, "input": c.input} for c in decision]
            out = len(json.dumps(content, ensure_ascii=False))
            return LLMResponse(content=content, text="", tool_calls=decision, input_tokens=size_in // 3,
                               output_tokens=out // 3, model=self.model)
        text = json.dumps(decision, ensure_ascii=False)
        return LLMResponse(content=[{"type": "text", "text": text}], text=text, input_tokens=size_in // 3,
                           output_tokens=len(text) // 3, model=self.model)

    # --- разбор контекста ---
    @staticmethod
    def _saved(context: str) -> dict | None:
        marker = "Результат выбранной проверки уже получен:"
        if marker not in context:
            return None
        line = context.split(marker, 1)[1].strip().splitlines()[0]
        try:
            return json.loads(line)
        except ValueError:
            return None

    @staticmethod
    def _call(name: str, **args) -> ToolCall:
        return ToolCall(id=f"mock_{uuid.uuid4().hex[:10]}", name=name, input=args)

    @staticmethod
    def _intent(text: str) -> str:
        low = text.lower()
        if low.startswith("подтверждаю заявку"):
            return "confirm"
        if "заявк" in low and re.search(r"созда|оформ|сдела|подготов|сформир", low):
            return "ticket"
        if re.search(r"результат|диагност", low) and re.search(r"получ|покаж|дай|запус|выда|что с", low):
            return "diagnose"
        return "question"

    @staticmethod
    def _unit_query(diagnosis: dict) -> str:
        code = diagnosis.get("anomaly_type") or ""
        unit = rules.FAULTS.get(code, {}).get("unit", "")
        return f"{diagnosis.get('anomaly_title') or ''} {unit} проверка регулировка неисправность"

    # --- выбор действия ---
    def _decide(self, text: str, session_id: str, saved: dict | None, results: dict, novice: bool = False):
        intent = self._intent(text)
        fresh = (results.get("get_diagnosis") or [None])[-1]
        known = fresh if fresh and "diagnosis" in fresh else saved
        passages = [r for res in results.get("search_manuals", []) for r in res.get("results", [])]

        if intent == "confirm":
            if "submit_ticket" not in results:
                draft = re.search(r"d_\d+", text)
                return [self._call("submit_ticket", draft_id=draft.group(0) if draft else "")]
            res = results["submit_ticket"][-1]
            if res.get("ok"):
                return self._answer(summary=f"Заявка {res['ticket_id']} создана в ТОиР.")
            return self._answer(summary=f"Заявка не отправлена. {res.get('reason', '')}")

        if intent == "diagnose":
            if "get_diagnosis" not in results:
                return [self._call("get_diagnosis", session_id=session_id)]
            if not fresh or "diagnosis" not in fresh:
                return self._answer(summary=f"Не удалось получить результат проверки. {(fresh or {}).get('error', '')}")
            return self._after_diagnosis(fresh, results, passages, novice)

        if intent == "ticket":
            if known is None:
                if "get_diagnosis" not in results:
                    return [self._call("get_diagnosis", session_id=session_id)]
                return self._answer(summary="Не удалось получить результат проверки, заявку оформить нельзя.")
            diagnosis, assessment = known["diagnosis"], known["assessment"]
            if "prepare_ticket" in results:
                res = results["prepare_ticket"][-1]
                if res.get("ok"):
                    return self._answer(summary="Черновик заявки готов. Проверьте состав и подтвердите отправку в ТОиР.")
                return self._answer(
                    summary=f"Заявку оформить нельзя. {res.get('reason', '')}",
                    limitations=[MOCK_NOTE],
                )
            if not assessment.get("ticket_allowed"):
                return [self._call("prepare_ticket", conclusion=diagnosis.get("anomaly_title") or "", operations=[], spare_parts=[])]
            if "search_manuals" not in results:
                return [self._call("search_manuals", query=self._unit_query(diagnosis))]
            code = diagnosis.get("anomaly_type")
            terms = set(tokens(self._unit_query(diagnosis)))
            operations = self._pick(passages, terms, CHECK_MARK, code, limit=3)
            unit = rules.FAULTS.get(code or "", {}).get("unit", "узел")
            return [self._call(
                "prepare_ticket",
                conclusion=f"{diagnosis.get('anomaly_title')}: требуется дефектовка, узел «{unit}»",
                operations=operations, spare_parts=[],
            )]

        # вопрос механика
        if "search_manuals" not in results:
            query = text
            if known and known["diagnosis"].get("anomaly_type") and len(tokens(text)) < 5:
                query += " " + rules.FAULTS.get(known["diagnosis"]["anomaly_type"], {}).get("unit", "")
            return [self._call("search_manuals", query=query)]
        terms = set(tokens(text))
        strong = [p for p in passages if len(terms & set(tokens(p["text"]))) >= max(2, round(len(terms) * 0.6))]
        checks = self._pick(strong, terms, CHECK_MARK, None, limit=3)
        if not checks and known and known["assessment"].get("outcome") == "check_failed":
            return self._answer(
                summary="По этой записи выводов о двигателе нет: она непригодна для анализа. Повторите запись, "
                        "после этого разберу результат.",
                limitations=[MOCK_NOTE],
            )
        if not checks:
            return self._answer(
                summary="В руководствах на двигатель этой машины ответа на этот вопрос нет. Рекомендую дефектовку.",
                limitations=["Поиск шёл только по руководствам двигателя выбранной машины.", MOCK_NOTE],
                not_found=True,
            )
        return self._answer(
            summary="Нашёл в руководстве на этот двигатель, смотрите пункты ниже.",
            checks=checks, limitations=[MOCK_NOTE],
        )

    def _after_diagnosis(self, fresh: dict, results: dict, passages: list[dict], novice: bool = False):
        diagnosis, assessment = fresh["diagnosis"], fresh["assessment"]
        outcome = assessment["outcome"]
        if outcome == "check_failed":
            return self._answer(summary="Запись непригодна для анализа. Выводов о двигателе нет, повторите запись.")
        if outcome == "normal":
            if "get_vehicle_history" not in results:
                return [self._call("get_vehicle_history")]
            history = results["get_vehicle_history"][-1]
            return self._answer(
                summary="Значимых отклонений не найдено, эксплуатацию можно продолжать.",
                observations=[diagnosis.get("description") or "", history.get("trend") or ""],
            )
        code = diagnosis.get("anomaly_type")
        unit = rules.FAULTS.get(code or "", {}).get("unit", "узел")
        observations = [
            f"Признаки по записи: {diagnosis.get('description')}",
            f"Оценка отклонения {rules.fmt(diagnosis.get('anomaly_score'))}, уверенность {rules.fmt(diagnosis.get('confidence'))}.",
        ]
        if novice:
            observations.append(
                f"Простыми словами: запись услышала признаки неполадки в узле «{unit}». "
                "Ниже по шагам, что проверить."
            )
        if assessment["flags"]["engine_mismatch"]:
            return self._answer(
                summary=f"Модель вернула тип «{diagnosis.get('anomaly_title')}», он не подходит двигателю этой машины. "
                        "Это ошибка модели, а не диагноз. Повторите проверку или проведите дефектовку.",
                limitations=["Нормативы другого двигателя не используются.", MOCK_NOTE], not_found=True,
            )
        if "search_manuals" not in results:
            return [self._call("get_vehicle_history"), self._call("search_manuals", query=self._unit_query(diagnosis))]
        history = (results.get("get_vehicle_history") or [{}])[-1]
        if history.get("trend"):
            observations.append(history["trend"])
        terms = set(tokens(self._unit_query(diagnosis)))
        checks = self._pick(passages, terms, CHECK_MARK, code, limit=3)
        used = {c["text"] for c in checks}
        repair = [r for r in self._pick(passages, terms, REPAIR_MARK, code, limit=3) if r["text"] not in used][:2]
        hypotheses = [f"Вероятная причина связана с узлом «{unit}». Это предположение по типу отклонения, а не вывод из руководства."]
        if not checks and not repair:
            return self._answer(
                summary=f"Проверка показала отклонение: {diagnosis.get('anomaly_title')}. "
                        "В руководстве на двигатель этой машины инструкции по этой неисправности не нашёл, рекомендую дефектовку.",
                observations=observations, hypotheses=hypotheses,
                limitations=["Нормативы другого двигателя не используются.", MOCK_NOTE], not_found=True,
            )
        return self._answer(
            summary=f"Проверка показала отклонение: {diagnosis.get('anomaly_title')}. {assessment.get('priority_action') or ''}.",
            observations=observations, hypotheses=hypotheses, checks=checks, repair=repair, limitations=[MOCK_NOTE],
        )

    # --- сборка ответа из фрагментов ---
    @staticmethod
    def _pick(passages: list[dict], terms: set[str], mark: re.Pattern, code: str | None, limit: int) -> list[dict]:
        candidates = []
        for passage in passages:
            if code and not rules.page_relevant(code, passage["text"]):
                continue
            for sentence in split_sentences(passage["text"]):
                if not 40 <= len(sentence) <= 300 or not mark.search(sentence.lower()):
                    continue
                overlap = len(set(tokens(sentence)) & terms)
                if overlap:
                    candidates.append((overlap, sentence, passage))
        candidates.sort(key=lambda c: c[0], reverse=True)
        out, seen = [], set()
        for _, sentence, passage in candidates:
            if sentence in seen:
                continue
            seen.add(sentence)
            out.append({"text": sentence, "refs": [
                {"manual_id": passage["manual_id"], "pdf_page": passage["pdf_page"], "quote": sentence}
            ]})
            if len(out) >= limit:
                break
        return out

    @staticmethod
    def _answer(summary: str, observations=None, hypotheses=None, checks=None, repair=None,
                limitations=None, not_found: bool = False) -> dict:
        return {
            "summary": summary,
            "observations": [o for o in (observations or []) if o],
            "hypotheses": hypotheses or [],
            "checks": checks or [],
            "repair": repair or [],
            "limitations": limitations or [],
            "conflicts": [],
            "not_found": not_found,
        }
