"""Инструменты агента (F5 ТЗ): диагностика, история, поиск по руководствам, заявка.

Каждый инструмент — отдельная функция. Какой из них вызвать, решает модель по контексту
диалога. Жёсткие правила (П1–П16) проверяются здесь, в коде: обойти их текстом модель не может.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Awaitable, Callable

from .. import clients, conflicts, fleet, rules
from ..config import Settings
from ..kb.index import Index
from ..kb.text import sanitize_description
from ..manuals import manual_by_id, manuals_for_engine
from ..store import Store
from .verify import Verifier

REF_SCHEMA = {
    "type": "object",
    "properties": {
        "manual_id": {"type": "string", "description": "Идентификатор документа из результатов поиска"},
        "pdf_page": {"type": "integer", "description": "Номер страницы PDF"},
        "quote": {"type": "string", "description": "Дословная цитата со страницы, одно-два предложения"},
    },
    "required": ["manual_id", "pdf_page", "quote"],
    "additionalProperties": False,
}
ITEM_SCHEMA = {
    "type": "object",
    "properties": {
        "text": {"type": "string"},
        "refs": {"type": "array", "items": REF_SCHEMA},
    },
    "required": ["text", "refs"],
    "additionalProperties": False,
}

STATEMENT_SCHEMA = {
    "type": "object",
    "properties": {
        "text": {"type": "string", "description": "Что утверждает этот источник, одной фразой"},
        "ref": REF_SCHEMA,
    },
    "required": ["text", "ref"],
    "additionalProperties": False,
}
CONFLICT_SCHEMA = {
    "type": "object",
    "properties": {
        "topic": {"type": "string", "description": "О чём расходятся источники, одной фразой без чисел"},
        "statements": {"type": "array", "items": STATEMENT_SCHEMA,
                       "description": "Не меньше двух формулировок, каждая со своей страницей и дословной цитатой"},
    },
    "required": ["topic", "statements"],
    "additionalProperties": False,
}

# Схема итогового ответа. Порядок полей повторяет порядок ответа из ТЗ (F4).
ANSWER_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string", "description": "Короткий вывод для механика, одна-три фразы. Число допустимо, "
                                                      "только если оно же стоит в пункте checks или repair с цитатой"},
        "observations": {"type": "array", "items": {"type": "string"},
                         "description": "Наблюдения: что показала проверка и история машины"},
        "hypotheses": {"type": "array", "items": {"type": "string"},
                       "description": "Инженерные гипотезы о причинах и рисках. Не из руководства, без чисел-нормативов"},
        "checks": {"type": "array", "items": ITEM_SCHEMA,
                   "description": "Проверки по руководству, по шагам. У каждого пункта ссылка с дословной цитатой"},
        "repair": {"type": "array", "items": ITEM_SCHEMA,
                   "description": "Возможный ремонт по руководству. У каждого пункта ссылка с дословной цитатой"},
        "limitations": {"type": "array", "items": {"type": "string"},
                        "description": "Ограничения: чего нет в руководстве, что требует решения механика"},
        "conflicts": {"type": "array", "items": CONFLICT_SCHEMA,
                      "description": "Противоречия между страницами или документами по одному вопросу. "
                                     "Пустой список, если противоречий нет"},
        "not_found": {"type": "boolean", "description": "true, если в руководствах этого двигателя ответа нет"},
    },
    "required": ["summary", "observations", "hypotheses", "checks", "repair", "limitations", "conflicts", "not_found"],
    "additionalProperties": False,
}

TOOLS = [
    {
        "name": "get_diagnosis",
        "description": (
            "Получить результат акустической проверки двигателя из ML-сервиса по номеру проверки этой машины. "
            "Возвращает статус, тип отклонения, оценку, уверенность, качество записи и оценку правил: приоритет, "
            "предупреждения, можно ли оформлять заявку. Вызывай, когда механик просит результат диагностики "
            "или когда для ответа нужен результат проверки, которого ещё нет в контексте."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"session_id": {"type": "string", "description": "Номер проверки, например S-0005"}},
            "required": ["session_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_vehicle_history",
        "description": (
            "История машины: прошлые проверки с оценками, тенденция, ранее созданные заявки. "
            "Вызывай, когда важно, повторяется ли отклонение и что уже делали с машиной."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
    },
    {
        "name": "search_manuals",
        "description": (
            "Поиск по руководствам на двигатель выбранной машины. Другие руководства недоступны. "
            "Запрос — слова из технической документации: узел, операция, параметр "
            "(«регулировка тепловых зазоров клапанов», «момент затяжки крышек коренных подшипников»). "
            "Коды F01…F14 в руководствах не встречаются, ищи по названию узла и признакам. "
            "Возвращает фрагменты с документом и номером страницы PDF. Можно вызывать несколько раз с разными запросами."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    {
        "name": "read_manual_page",
        "description": (
            "Прочитать страницу руководства целиком. Нужна, когда фрагмент обрывается, для таблиц и соседних страниц."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"manual_id": {"type": "string"}, "pdf_page": {"type": "integer"}},
            "required": ["manual_id", "pdf_page"],
            "additionalProperties": False,
        },
    },
    {
        "name": "prepare_ticket",
        "description": (
            "Собрать черновик заявки на дефектовку для ТОиР. Вызывай только по команде механика создать заявку. "
            "Работы и запчасти берутся только из руководства на двигатель этой машины: у каждого пункта ссылка "
            "с дословной цитатой. Приоритет назначает система по правилам. Черновик увидит механик и подтвердит сам. "
            "Если инструмент вернул отказ, объясни механику причину и не повторяй вызов с выдуманными ссылками."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "conclusion": {"type": "string", "description": "Диагноз одной-двумя фразами, без нормативов"},
                "operations": {"type": "array", "items": ITEM_SCHEMA, "description": "Работы по дефектовке, по шагам"},
                "spare_parts": {"type": "array", "items": ITEM_SCHEMA,
                                "description": "Запчасти и материалы из руководства. Может быть пустым"},
            },
            "required": ["conclusion", "operations", "spare_parts"],
            "additionalProperties": False,
        },
    },
    {
        "name": "submit_ticket",
        "description": (
            "Отправить подтверждённый черновик заявки в ТОиР и получить номер. Работает только после того, "
            "как механик подтвердил именно этот черновик в интерфейсе."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"draft_id": {"type": "string"}},
            "required": ["draft_id"],
            "additionalProperties": False,
        },
    },
]

Emit = Callable[[dict], Awaitable[None]]


@dataclass
class TurnContext:
    vehicle: dict
    session_id: str
    store: Store
    index: Index
    settings: Settings
    emit: Emit
    diagnosis: dict | None = None
    assessment: dict | None = None
    diagnosed_this_turn: bool = False
    draft: dict | None = None
    ticket: dict | None = None
    ticket_block: str | None = None          # причина отказа в заявке, если был
    no_instruction: bool = False             # в руководстве нет применимой инструкции (П10)
    confirmed_draft_id: str | None = None    # черновик, который механик подтвердил в интерфейсе
    warning_ack: bool = False
    steps: list[dict] = field(default_factory=list)
    searched: bool = False
    seen_calls: set[str] = field(default_factory=set)   # вызовы инструментов этого хода: защита от зацикливания
    photos: int = 0                          # сколько фото механика видит модель в этом ходе

    @property
    def allowed_manuals(self) -> list[str]:
        return [m.id for m in manuals_for_engine(self.vehicle["engine_model"])]

    @property
    def kb_empty(self) -> bool:
        """Руководства этого двигателя не проиндексированы: это ошибка настройки, а не «инструкции нет»."""
        return all(self.index.page_count(manual_id) == 0 for manual_id in self.allowed_manuals)

    def context_numbers(self) -> set[str]:
        """Числа, которые агент вправе назвать без страницы руководства: результат проверки и история."""
        from .verify import _norm, page_numbers

        values: set[str] = set()
        sessions = list(self.vehicle.get("sessions", []))
        if self.diagnosis:
            sessions.append(self.diagnosis)
        for s in sessions:
            for key in ("anomaly_score", "confidence"):
                if s.get(key) is not None:
                    values.add(_norm(f"{s[key]:.2f}"))
                    values.add(str(round(s[key] * 100)))
        values.add(_norm(str(self.settings.confidence_min)))
        values.add(str(round(self.settings.confidence_min * 100)))
        values |= page_numbers(self.vehicle.get("engine_model", ""))
        # Обозначения документов, модель и номера машины, основание приоритета и пороги из оценки правил.
        card = [fleet.title_of(self.vehicle), str(self.vehicle.get("garage_no", "")), self.vehicle["vehicle_id"]]
        card += [f"{m.designation} {m.short} {m.title}" for m in manuals_for_engine(self.vehicle["engine_model"])]
        if self.assessment:
            card += [*self.assessment.get("basis", []), *self.assessment.get("warnings", []),
                     str(self.assessment.get("ticket_block_reason") or "")]
        values |= page_numbers(" ".join(card))
        values.add(str(len(self.vehicle.get("sessions", []))))
        return values

    def verifier(self) -> Verifier:
        return Verifier(self.index, self.allowed_manuals, self.context_numbers())

    async def step(self, step_id: str, tool: str, title: str, status: str, detail: str = "") -> None:
        record = {"id": step_id, "tool": tool, "title": title, "status": status, "detail": detail}
        for i, existing in enumerate(self.steps):
            if existing["id"] == step_id:
                self.steps[i] = record
                break
        else:
            self.steps.append(record)
        await self.emit({"type": "step", **record})


def _dump(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False)


def _outcome_instruction(assessment: dict) -> str:
    outcome = assessment["outcome"]
    if outcome == "check_failed":
        return ("Запись непригодна. Не делай выводов о двигателе, не называй причин и не ищи в руководствах. "
                "Попроси повторить запись. Заявка невозможна.")
    if outcome == "normal":
        return "Отклонений нет: сообщи, что по этой проверке значимых отклонений нет и заявка не нужна; решение о выпуске за механиком. Передай предупреждения из поля warnings, если они есть."
    if assessment["flags"]["engine_mismatch"]:
        return ("Тип неисправности не подходит двигателю машины. Карточка машины важнее результата модели: "
                "это ошибка модели диагностики, а не диагноз. Сообщи механику о расхождении. Диагноз по этому типу "
                "не ставь, причин не называй, в руководствах не ищи, тип на похожий не заменяй. "
                "Рекомендуй повторить проверку или провести дефектовку. Заявка невозможна.")
    text = "Объясни отклонение и риск, найди в руководствах проверки и нормативы со страницами."
    if assessment["warnings"]:
        text += " Обязательно сообщи механику предупреждения из поля warnings."
    if not assessment["ticket_allowed"]:
        text += " Заявку оформлять нельзя, причина в поле ticket_block_reason."
    return text


INJECTION_NOTE = "в описании был посторонний текст, он отброшен"


def _webhook_result(vehicle_id: str, session_id: str, error: clients.ServiceError) -> dict | None:
    """Результат проверки, который «НейроДВС» передал веб-хуком. Нужен, когда ML-сервис эту проверку
    не знает (404) или недоступен. Проверки из файла заказчика сюда не попадают: их знает ML-сервис."""
    if error.status not in (None, 404):
        return None
    meta = fleet.repo().check_meta(vehicle_id, session_id)
    if not meta or meta["source"] != "api" or not meta["has_result"] or not meta["session"].get("status"):
        return None
    return {k: v for k, v in meta["session"].items() if k != "checked_at"}


async def get_diagnosis(ctx: TurnContext, args: dict, step_id: str) -> tuple[str, bool]:
    session_id = str(args.get("session_id") or ctx.session_id)
    title = f"Получаю результат проверки {session_id}"
    await ctx.step(step_id, "get_diagnosis", title, "running")
    if fleet.get_session(ctx.vehicle, session_id) is None:
        await ctx.step(step_id, "get_diagnosis", title, "error", "у машины нет такой проверки")
        return _dump({"error": f"У машины {ctx.vehicle['vehicle_id']} нет проверки {session_id}"}), True
    via = "POST /diagnose → 200"
    try:
        diagnosis = await clients.diagnose(ctx.vehicle["vehicle_id"], session_id)
    except clients.ServiceError as exc:
        # Запасной путь: результат пришёл веб-хуком «НейроДВС» (/api/v1/checks), а ML-сервис эту проверку не знает
        diagnosis = _webhook_result(ctx.vehicle["vehicle_id"], session_id, exc)
        if diagnosis is None:
            await ctx.step(step_id, "get_diagnosis", title, "error", str(exc))
            return _dump({"error": str(exc)}), True
        via = "результат из веб-хука НейроДВС"
    else:
        # Проверка пришла веб-хуком без результата: теперь он есть и в сводке парка
        fleet.repo().fill_result(ctx.vehicle["vehicle_id"], session_id, diagnosis)
    session = fleet.get_session(ctx.vehicle, session_id)
    diagnosis["checked_at"] = session.get("checked_at")
    # П17: описание от ML-сервиса — данные. Посторонние указания в нём отбрасываются до модели и до экрана.
    diagnosis["description"], flagged = sanitize_description(diagnosis.get("description") or "")
    diagnosis["description_flagged"] = flagged
    previous = fleet.previous_sessions(ctx.vehicle, session_id)
    assessment = rules.assess(diagnosis, ctx.vehicle, previous, ctx.settings.confidence_min)
    repeat = rules.repeat_after_repair(diagnosis, ctx.store.tickets(ctx.vehicle["vehicle_id"]), session_id)
    if repeat:
        assessment["warnings"].append(repeat)
    ctx.session_id = session_id
    ctx.diagnosis, ctx.assessment, ctx.diagnosed_this_turn = diagnosis, assessment, True
    ctx.store.save_analysis(ctx.vehicle["vehicle_id"], session_id, diagnosis, assessment)
    detail = f"{via}, {diagnosis['status']}"
    if diagnosis.get("anomaly_type"):
        detail += f" {diagnosis['anomaly_type']}"
    # Механику предупреждение о подложенном тексте не нужно: на вывод оно не влияет. Видно в ходе разбора
    # и в журнале администратора (флаг остаётся в сохранённом результате проверки).
    if flagged:
        detail += f"; {INJECTION_NOTE}"
    await ctx.step(step_id, "get_diagnosis", title, "done", detail)
    return _dump({
        "diagnosis": {k: v for k, v in diagnosis.items() if k != "description_flagged"},
        "assessment": assessment,
        "what_to_do": _outcome_instruction(assessment),
    }), False


async def get_vehicle_history(ctx: TurnContext, args: dict, step_id: str) -> tuple[str, bool]:
    title = "Смотрю историю машины"
    await ctx.step(step_id, "get_vehicle_history", title, "running")
    tickets = ctx.store.tickets(ctx.vehicle["vehicle_id"])
    sessions = [
        {k: s.get(k) for k in ("session_id", "checked_at", "status", "anomaly_type", "anomaly_title",
                               "anomaly_score", "confidence", "signal_quality")}
        for s in ctx.vehicle["sessions"]
    ]
    # Тенденция считается до выбранной проверки включительно: более поздние проверки на неё не влияют.
    upto = fleet.previous_sessions(ctx.vehicle, ctx.session_id)
    current = fleet.get_session(ctx.vehicle, ctx.session_id)
    trend = rules.trend(upto + ([current] if current else []))
    await ctx.step(step_id, "get_vehicle_history", title, "done",
                   f"проверок: {len(sessions)}, заявок: {len(tickets)}; {trend['text']}")
    return _dump({
        "selected_session": ctx.session_id,
        "sessions": sessions,
        "trend": trend["text"],
        "tickets": [
            {"ticket_id": t["ticket_id"], "session_id": t["session_id"], "created_at": t["created_at"],
             "anomaly_type": t.get("anomaly_type"), "conclusion": t["conclusion"], "urgency": t["urgency"],
             "operations": t.get("operations", []), "spare_parts": t.get("spare_parts", [])}
            for t in tickets
        ],
    }), False


async def search_manuals(ctx: TurnContext, args: dict, step_id: str) -> tuple[str, bool]:
    query = str(args.get("query", "")).strip()
    title = f"Ищу в руководствах: {query[:70]}"
    await ctx.step(step_id, "search_manuals", title, "running")
    if ctx.kb_empty:
        ctx.searched = True
        await ctx.step(step_id, "search_manuals", title, "error", "руководства не загружены в базу знаний")
        return _dump({"error": f"Руководства на двигатель {ctx.vehicle['engine_model']} не загружены в базу знаний. "
                               "Это ошибка настройки стенда. Скажи механику, что ответить по руководству сейчас нельзя. "
                               "Не говори, что инструкции в руководстве нет."}), True
    hits = ctx.index.search(query, ctx.allowed_manuals, limit=6, every_manual=True)
    ctx.searched = True
    results = []
    for hit in hits:
        manual = manual_by_id(hit["manual_id"])
        results.append({
            "manual_id": hit["manual_id"], "document": manual.designation,
            "pdf_page": hit["pdf_page"], "text": hit["text"],
        })
    engine = ctx.vehicle["engine_model"]
    if results:
        found = ", ".join(f"{manual_by_id(r['manual_id']).short} стр. {r['pdf_page']}" for r in results[:4])
        await ctx.step(step_id, "search_manuals", title, "done", f"найдено фрагментов: {len(results)}; {found}")
        note = f"Поиск шёл только по руководствам двигателя {engine}."
    else:
        await ctx.step(step_id, "search_manuals", title, "done", "ничего не найдено")
        note = (f"В руководствах двигателя {engine} по этому запросу ничего не найдено. "
                "Попробуй другие слова. Если и так пусто, честно скажи, что данных нет.")
    payload = {"results": results, "note": note}
    known = conflicts.from_registry(ctx.index, ctx.allowed_manuals, query, [])
    if known:
        # П18: по этой теме расхождение документов подтверждено. Модель должна знать о нём до ответа.
        payload["known_conflicts"] = [
            {"topic": block["topic"],
             "pages": [f"{s['ref']['manual_id']} стр. {s['ref']['pdf_page']}" for s in block["statements"]]}
            for block in known
        ]
        payload["note"] += (" По теме из known_conflicts документы расходятся, это подтверждено: не пиши, что источники "
                            "согласны, и не выбирай одну формулировку. Блок расхождения система покажет сама.")
    return _dump(payload), False


async def read_manual_page(ctx: TurnContext, args: dict, step_id: str) -> tuple[str, bool]:
    manual_id = str(args.get("manual_id", ""))
    page = int(args.get("pdf_page") or 0)
    manual = manual_by_id(manual_id)
    title = f"Открываю {manual.short if manual else manual_id}, стр. {page}"
    await ctx.step(step_id, "read_manual_page", title, "running")
    if manual is None or manual_id not in ctx.allowed_manuals:
        await ctx.step(step_id, "read_manual_page", title, "error", "документ другого двигателя недоступен")
        return _dump({"error": "Этот документ не относится к двигателю выбранной машины и недоступен"}), True
    text = ctx.index.page_text(manual_id, page)
    if text is None:
        await ctx.step(step_id, "read_manual_page", title, "error", "нет такой страницы")
        return _dump({"error": f"В документе {manual.designation} нет страницы {page}"}), True
    await ctx.step(step_id, "read_manual_page", title, "done", f"{len(text)} символов")
    return _dump({"manual_id": manual_id, "document": manual.designation, "pdf_page": page, "text": text[:9000]}), False


async def ensure_diagnosis(ctx: TurnContext) -> None:
    """Результат проверки для выбранной проверки: из памяти приложения, если уже получали."""
    if ctx.diagnosis is None:
        saved = ctx.store.analysis(ctx.vehicle["vehicle_id"], ctx.session_id)
        if saved:
            ctx.diagnosis, ctx.assessment = saved["diagnosis"], saved["assessment"]


async def prepare_ticket(ctx: TurnContext, args: dict, step_id: str) -> tuple[str, bool]:
    title = "Собираю черновик заявки"
    await ctx.step(step_id, "prepare_ticket", title, "running")
    await ensure_diagnosis(ctx)
    if ctx.diagnosis is None or ctx.assessment is None:
        await ctx.step(step_id, "prepare_ticket", title, "error", "нет результата проверки")
        return _dump({"refused": True, "reason": "Сначала получи результат диагностики этой проверки (get_diagnosis)."}), True

    assessment = ctx.assessment
    if not assessment["ticket_allowed"]:
        ctx.ticket_block = assessment["ticket_block_reason"]
        await ctx.step(step_id, "prepare_ticket", title, "error", "заявка не допускается правилами")
        return _dump({"refused": True, "reason": assessment["ticket_block_reason"],
                      "what_to_do": "Объясни причину механику. Заявку не оформляй."}), True

    verifier = ctx.verifier()
    operations, problems = verifier.check_items(args.get("operations"), "Работы")
    parts, part_problems = verifier.check_items(args.get("spare_parts"), "Запчасти")
    code = ctx.diagnosis["anomaly_type"]
    relevant = any(
        rules.page_relevant(code, verifier.page(ref["manual_id"], ref["pdf_page"]) or "")
        for item in operations for ref in item["refs"]
    )
    engine = ctx.vehicle["engine_model"]
    if not operations or not relevant:
        ctx.no_instruction = True
        ctx.ticket_block = (
            f"В руководстве на двигатель {engine} нет применимой инструкции по найденной неисправности: "
            "заявка в ТОиР не отправляется."
        )
        why = "; ".join(problems) if problems else "страницы ссылок не относятся к узлу этой неисправности"
        await ctx.step(step_id, "prepare_ticket", title, "error", "нет подтверждённых работ по руководству")
        return _dump({
            "refused": True, "reason": ctx.ticket_block, "details": why,
            "what_to_do": ("Если в руководстве есть процедура проверки именно этого узла, найди её поиском и повтори "
                           "вызов с дословной цитатой. Если нет, скажи механику, что инструкции нет, и рекомендуй дефектовку."),
        }), True

    conclusion = str(args.get("conclusion", "")).strip() or ctx.diagnosis.get("anomaly_title") or ""
    _, conclusion_problems = verifier.check_free_text([conclusion], "Диагноз", set())
    if conclusion_problems:
        conclusion = f"{ctx.diagnosis.get('anomaly_title')}: требуется дефектовка узла"

    references, seen = [], set()
    for item in operations + parts:
        for ref in item["refs"]:
            key = (ref["manual_id"], ref["pdf_page"])
            if key not in seen:
                seen.add(key)
                references.append({"manual": ref["designation"], "manual_id": ref["manual_id"],
                                   "short": ref["short"], "pdf_page": ref["pdf_page"]})

    warnings = list(assessment["warnings"])
    # П18: если работа опирается на спорную формулировку, механик видит это до подтверждения заявки.
    disputes = conflicts.from_registry(ctx.index, ctx.allowed_manuals, "", operations + parts)
    conflicts.mark_disputed(operations + parts, disputes)
    warnings += [conflicts.warning_line(block) for block in disputes]
    earlier = [t for t in ctx.store.tickets(ctx.vehicle["vehicle_id"]) if t["session_id"] == ctx.session_id]
    if earlier:
        warnings.append(f"По этой проверке уже создана заявка {earlier[-1]['ticket_id']}.")

    draft = ctx.store.create_draft(ctx.vehicle["vehicle_id"], ctx.session_id, {
        "vehicle_id": ctx.vehicle["vehicle_id"],
        "session_id": ctx.session_id,
        "anomaly_type": code,
        "anomaly_title": ctx.diagnosis.get("anomaly_title"),
        "conclusion": conclusion,
        "urgency": assessment["priority"],
        "urgency_basis": assessment["basis"],
        "operations": operations,
        "spare_parts": parts,
        "references": references,
        "requires_warning_ack": assessment["flags"]["quality_warning"],
        "warnings": warnings,
    })
    ctx.draft = draft
    dropped = problems + part_problems
    await ctx.step(step_id, "prepare_ticket", title, "done",
                   f"работ: {len(operations)}, запчастей: {len(parts)}, источников: {len(references)}")
    return _dump({
        "ok": True, "draft_id": draft["draft_id"], "urgency": draft["urgency"],
        "kept_operations": len(operations), "kept_spare_parts": len(parts),
        "dropped": dropped,
        "what_to_do": "Черновик показан механику. Коротко скажи, что он готов, и попроси проверить и подтвердить.",
    }), False


DISPUTED_NOTE = " (в руководствах расхождение по условию этой работы: выполнять по более осторожной формулировке)"


def _ticket_line(item: dict) -> str:
    """Текст работы для ТОиР. Предупреждения черновика в контракт ТОиР не входят, поэтому пометка о спорном
    условии идёт в саму строку работы: исполнитель в цехе видит её без черновика."""
    return item["text"] + (DISPUTED_NOTE if item.get("disputed") else "")


def ticket_payload(draft: dict) -> dict:
    """JSON заявки строго по контракту Mock ТОиР (раздел 5 ТЗ)."""
    return {
        "vehicle_id": draft["vehicle_id"],
        "session_id": draft["session_id"],
        "anomaly_type": draft["anomaly_type"],
        "conclusion": draft["conclusion"],
        "urgency": draft["urgency"],
        "operations": [_ticket_line(item) for item in draft["operations"]],
        "spare_parts": [_ticket_line(item) for item in draft["spare_parts"]],
        "references": [{"manual": ref["manual"], "pdf_page": ref["pdf_page"]} for ref in draft["references"]],
    }


async def submit_ticket(ctx: TurnContext, args: dict, step_id: str) -> tuple[str, bool]:
    draft_id = str(args.get("draft_id", ""))
    title = "Отправляю заявку в ТОиР"
    await ctx.step(step_id, "submit_ticket", title, "running")

    async def refuse(reason: str) -> tuple[str, bool]:
        await ctx.step(step_id, "submit_ticket", title, "error", reason)
        return _dump({"refused": True, "reason": reason}), True

    draft = ctx.store.draft(draft_id)
    if draft is None or draft["vehicle_id"] != ctx.vehicle["vehicle_id"]:
        return await refuse("Черновик не найден.")
    # П14: отправка только после подтверждения именно этого черновика механиком.
    if ctx.confirmed_draft_id != draft_id:
        return await refuse("Механик ещё не подтвердил этот черновик. Заявка не отправлена.")
    if draft["status"] == "sent":
        return await refuse(f"Заявка уже отправлена: {draft['ticket_id']}.")
    if draft["requires_warning_ack"] and not ctx.warning_ack:
        return await refuse("Запись с помехами: нужно явное согласие механика с предупреждением.")
    saved = ctx.store.analysis(draft["vehicle_id"], draft["session_id"])
    if not saved or not saved["assessment"]["ticket_allowed"]:
        return await refuse("Для этой проверки заявка не допускается правилами.")
    if saved["diagnosis"].get("anomaly_type") != draft["anomaly_type"]:
        return await refuse("Тип неисправности в черновике не совпадает с результатом проверки.")
    if not draft["operations"] or not draft["references"] or not draft["conclusion"].strip():
        return await refuse("В заявке нет работ, источников или диагноза.")

    try:
        response = await clients.create_ticket(ticket_payload(draft))
    except clients.ServiceError as exc:
        return await refuse(str(exc))
    ticket = ctx.store.add_ticket({
        **ticket_payload(draft), "ticket_id": response["ticket_id"], "draft_id": draft_id,
        "anomaly_title": draft.get("anomaly_title"), "urgency_basis": draft.get("urgency_basis", []),
    })
    draft.update(status="sent", ticket_id=response["ticket_id"])
    ctx.store.save_draft(draft)
    ctx.ticket, ctx.draft = ticket, draft
    await ctx.step(step_id, "submit_ticket", title, "done", f"POST /tickets → 201, {response['ticket_id']}")
    return _dump({"ok": True, "ticket_id": response["ticket_id"], "status": response.get("status")}), False


HANDLERS = {
    "get_diagnosis": get_diagnosis,
    "get_vehicle_history": get_vehicle_history,
    "search_manuals": search_manuals,
    "read_manual_page": read_manual_page,
    "prepare_ticket": prepare_ticket,
    "submit_ticket": submit_ticket,
}


async def run_tool(ctx: TurnContext, name: str, args: dict, step_id: str) -> tuple[str, bool]:
    handler = HANDLERS.get(name)
    if handler is None:
        return _dump({"error": f"Неизвестный инструмент {name}"}), True
    # Слабая модель может повторять один и тот же вызов по кругу. Второй раз инструмент не выполняется:
    # модель получает подсказку и должна пойти дальше.
    key = name + json.dumps(args, ensure_ascii=False, sort_keys=True)
    if key in ctx.seen_calls:
        return _dump({"error": "Этот вызов с теми же параметрами уже выполнен в этом ходе, его результат есть выше. "
                               "Не повторяй его: вызови другой инструмент или дай итоговый ответ."}), True
    ctx.seen_calls.add(key)
    try:
        return await handler(ctx, args, step_id)
    except Exception as exc:  # сбой инструмента не должен ронять ход агента
        await ctx.step(step_id, name, name, "error", f"сбой: {exc.__class__.__name__}")
        return _dump({"error": f"Сбой инструмента: {exc}"}), True
