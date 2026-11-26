"""Правила, которые держит код, а не модель: исход проверки, приоритет, допуск заявки.

Номера правил (П5, П7 и т. д.) соответствуют docs/requirements.md.
"""
from __future__ import annotations

from .kb.text import stem, tokens

LEVELS = ["low", "medium", "high"]
LABELS = {"low": "низкий", "medium": "средний", "high": "высокий"}
BASE_LABELS = {"low": "низкая", "medium": "средняя", "high": "высокая"}

# Что приоритет значит для автопарка (ответ ментора 26.11, правило П11).
ACTIONS = {
    "high": "На дефектовку до выпуска в рейс",
    "medium": "Дефектовка на ближайшее ТО, работа под наблюдением",
    "low": "Машина работает, узел проверяется на следующей проверке",
}

QUALITY_LABELS = {"good": "хорошее", "warning": "с помехами", "bad": "плохое"}

# Базовая критичность типа неисправности (правило П12). Заказчик на кик-оффе назвал два критерия:
# высокий приоритет — безопасность и готовность к рейсу (тормоза, коробка), в остальном важнее то,
# что дороже в ремонте при развитии дефекта. Поле why объясняет выбор механику.
# keywords — слова, по которым страница
# относится к узлу (правило П9). fuels: для какого топлива тип вообще возможен (П16).
FAULTS: dict[str, dict] = {
    "F01": {"base": "medium", "why": "при развитии дефекта ремонт головки и клапанов дорогой, в плановое ТО он дешевле",
            "unit": "клапанный механизм",
            "keywords": [["клапан"], ["коромысло"], ["толкатель"], ["штанга"]]},
    "F02": {"base": "high", "why": "без давления масла двигатель быстро выходит из строя, это самый дорогой ремонт",
            "unit": "система смазки",
            "keywords": [["масло", "давление"], ["масляный", "насос"], ["система", "смазки"]]},
    "F03": {"base": "high", "why": "перегрев и жидкость в масле быстро приводят к дорогому ремонту двигателя",
            "unit": "система охлаждения",
            "keywords": [["перегрев"], ["охлаждающая"], ["охлаждение"], ["термостат"], ["прокладка", "головка"]]},
    "F04": {"base": "low", "why": "ремонт недорогой, на выпуск в рейс обычно не влияет",
            "unit": "ремённый привод агрегатов",
            "keywords": [["ремень"], ["ремня"], ["шкив"]]},
    "F05": {"base": "low", "why": "ремонт недорогой, на выпуск в рейс обычно не влияет",
            "unit": "генератор", "keywords": [["генератор"]]},
    "F06": {"base": "medium", "why": "влияет на эксплуатацию, ремонт можно запланировать",
            "unit": "сцепление", "keywords": [["сцепление"]]},
    "F07": {"base": "high", "why": "коробка передач прямо влияет на эксплуатацию и безопасность",
            "unit": "коробка передач", "keywords": [["коробка", "передач"]]},
    "F08": {"base": "medium", "why": "влияет на работу двигателя, ремонт можно запланировать",
            "unit": "дизельная топливная аппаратура", "fuels": ["дизель"],
            "keywords": [["тнвд"], ["форсунка"], ["топливный", "насос"], ["впрыск"], ["топливоподача"]]},
    "F09": {"base": "medium", "why": "ремонт турбокомпрессора дорогой, его лучше запланировать заранее",
            "unit": "турбокомпрессор",
            "keywords": [["турбокомпрессор"], ["наддув"]]},
    "F10": {"base": "high", "why": "тормоза и рулевое управление: безопасность",
            "unit": "компрессор пневмотормозов, насос ГУР",
            "keywords": [["компрессор", "тормоза"], ["воздушный", "компрессор"], ["пневматический", "компрессор"],
                         ["гидроусилитель"], ["насос", "гур"]]},
    "F11": {"base": "low", "why": "ремонт недорогой, на выпуск в рейс обычно не влияет",
            "unit": "рециркуляция отработавших газов", "keywords": [["рециркуляция"]]},
    "F12": {"base": "medium", "why": "влияет на работу двигателя, ремонт можно запланировать",
            "unit": "система зажигания", "fuels": ["бензин"],
            "keywords": [["зажигание"], ["свеча"], ["катушка"]]},
    "F13": {"base": "medium", "why": "влияет на работу двигателя, ремонт можно запланировать",
            "unit": "подача бензина", "fuels": ["бензин"],
            "keywords": [["бензонасос"], ["топливный", "насос"], ["форсунка"], ["топливо", "подача"], ["топливная", "рампа"]]},
    "F14": {"base": "medium", "why": "обрыв цепи ведёт к дорогому ремонту двигателя, замену лучше запланировать заранее",
            "unit": "цепной привод ГРМ",
            "keywords": [["цепь"], ["цепи"], ["гидронатяжитель"], ["звездочка"]]},
}

SCORE_HIGH = 0.85  # с этой оценки приоритет поднимается на ступень
SCORE_LOW = 0.62   # ниже этой оценки приоритет опускается на ступень
CONFIDENCE_CAP = 0.60  # ниже этой уверенности приоритет не выше среднего
TREND_STEP = 0.03


def fmt(value: float | None) -> str:
    if value is None:
        return "нет"
    return f"{value:.2f}".replace(".", ",")


def _keyword_stems(code: str) -> list[set[str]]:
    return [{stem(w.lower().replace("ё", "е")) for w in group} for group in FAULTS[code]["keywords"]]


def page_relevant(code: str, page_text: str) -> bool:
    """Правило П9: страница прямо относится к узлу, на который указывает тип неисправности."""
    if code not in FAULTS:
        return False
    page = set(tokens(page_text))
    return any(group <= page for group in _keyword_stems(code))


def valid_sessions(sessions: list[dict]) -> list[dict]:
    return [s for s in sessions if s.get("status") != "check_failed" and s.get("anomaly_score") is not None]


def trend(sessions: list[dict]) -> dict:
    """Тенденция оценки отклонения по последним проверкам (задача B2)."""
    scores = [s["anomaly_score"] for s in valid_sessions(sessions)][-5:]
    if len(scores) < 2:
        return {"direction": "none", "text": "Для тенденции мало проверок с пригодной записью"}
    run_up = run_down = 1
    for prev, cur in zip(reversed(scores[:-1]), reversed(scores[1:])):
        if cur - prev >= TREND_STEP and run_down == 1:
            run_up += 1
        elif prev - cur >= TREND_STEP and run_up == 1:
            run_down += 1
        else:
            break
    if run_up >= 2:
        return {"direction": "rising",
                "text": f"Оценка отклонения растёт {run_up} проверки подряд: с {fmt(scores[-run_up])} до {fmt(scores[-1])}"}
    if run_down >= 2:
        return {"direction": "falling",
                "text": f"Оценка отклонения снижается: с {fmt(scores[-run_down])} до {fmt(scores[-1])}"}
    return {"direction": "stable", "text": f"Оценка отклонения без выраженной тенденции, последняя {fmt(scores[-1])}"}


def assess(diag: dict, vehicle: dict, previous: list[dict], confidence_min: float) -> dict:
    """Оценка результата проверки: исход, приоритет с основанием, можно ли оформлять заявку.

    previous: проверки этой машины раньше текущей, от ранней к поздней.
    """
    status = diag.get("status")
    quality = diag.get("signal_quality")
    score = diag.get("anomaly_score")
    conf = diag.get("confidence")
    code = diag.get("anomaly_type")
    flags = {
        "check_failed": status == "check_failed" or quality == "bad",
        "quality_warning": quality == "warning",
        "low_confidence": False,
        "engine_mismatch": False,
    }
    result = {
        "outcome": "check_failed" if flags["check_failed"] else status,
        "priority": None, "priority_label": None, "priority_action": None,
        "basis": [], "flags": flags, "warnings": [],
        "ticket_allowed": False, "ticket_block_reason": None,
        "confidence_min": confidence_min,
    }

    # П5: сбой записи или качество bad. Выводов и заявки нет, без исключений.
    if flags["check_failed"]:
        result["ticket_block_reason"] = (
            "Запись непригодна для анализа: выводы о двигателе не делаются, заявка не оформляется. Повторите запись."
        )
        return result

    if status == "normal":
        if flags["quality_warning"]:
            result["warnings"].append("Запись с помехами: результат «норма» предварительный, при сомнениях повторите запись.")
        result["ticket_block_reason"] = "Отклонений не найдено, заявка не нужна."  # П8
        return result

    fault = FAULTS.get(code or "")
    title = diag.get("anomaly_title") or code or "неизвестный тип"
    if fault is None:
        result["ticket_block_reason"] = f"Тип неисправности {code} отсутствует в справочнике."
        return result

    # П16: тип неисправности невозможен для этого топлива. Карточка машины важнее результата модели:
    # это ошибка модели, а не диагноз. Приоритета и заявки нет.
    fuels = fault.get("fuels")
    if fuels and vehicle.get("fuel") not in fuels:
        flags["engine_mismatch"] = True
        engine = vehicle.get("engine_model")
        result["warnings"].append(
            f"Модель диагностики вернула тип «{title}» ({code}). Он не подходит двигателю {engine} "
            f"({vehicle.get('fuel')}). Карточка машины важнее результата модели."
        )
        result["basis"].append("Приоритет не назначен: результат считается ошибкой модели, а не диагнозом")
        result["ticket_block_reason"] = (
            f"До уточнения данных заявка в ТОиР не оформляется: в руководстве на двигатель {engine} "
            "нет инструкции по такому типу неисправности."
        )
        return result

    # П12: базовая критичность типа и ограниченная поправка по оценке отклонения.
    base = fault["base"]
    basis = [f"Базовая критичность типа {code} «{title}»: {BASE_LABELS[base]} ({fault['why']})"]
    shift = 0
    if score is not None and score >= SCORE_HIGH:
        shift = 1
        basis.append(f"Оценка отклонения {fmt(score)} высокая (от {fmt(SCORE_HIGH)}): приоритет на ступень выше")
    elif score is not None and score < SCORE_LOW:
        shift = -1
        basis.append(f"Оценка отклонения {fmt(score)} близка к порогу (ниже {fmt(SCORE_LOW)}): приоритет на ступень ниже")
    else:
        basis.append(f"Оценка отклонения {fmt(score)}: без поправки")

    same = [s for s in valid_sessions(previous) if s.get("anomaly_type") == code]
    if same and score is not None:
        last = same[-1]
        if score - last["anomaly_score"] >= TREND_STEP:
            basis.append(
                f"Тот же тип был в проверке {last['session_id']} с оценкой {fmt(last['anomaly_score'])}: отклонение растёт"
            )
            shift = min(1, shift + 1)
        else:
            basis.append(f"Тот же тип уже был в проверке {last['session_id']}: отклонение повторяется")

    level = max(0, min(2, LEVELS.index(base) + max(-1, min(1, shift))))

    # П6: помехи показываются всегда. П7: порог уверенности.
    if flags["quality_warning"]:
        result["warnings"].append("Запись с помехами, уверенность модели снижена: вывод предварительный.")
    if conf is not None and conf < confidence_min:
        flags["low_confidence"] = True
        result["warnings"].append(
            f"Уверенность модели {fmt(conf)} ниже порога {fmt(confidence_min)}: нужна повторная проверка, заявка не оформляется."
        )
    if (flags["quality_warning"] or (conf is not None and conf < CONFIDENCE_CAP)) and level > 1:
        level = 1
        basis.append(f"Запись с помехами или уверенность ниже {fmt(CONFIDENCE_CAP)}: приоритет не выше среднего")
    basis.append(f"Уверенность модели {fmt(conf)}, качество записи: {QUALITY_LABELS.get(quality, quality)}")

    priority = LEVELS[level]
    result.update(priority=priority, priority_label=LABELS[priority], priority_action=ACTIONS[priority], basis=basis)

    if flags["low_confidence"]:
        result["ticket_block_reason"] = (
            f"Уверенность модели {fmt(conf)} ниже порога {fmt(confidence_min)}. Повторите проверку, заявка не оформляется."
        )
    else:
        result["ticket_allowed"] = True
    return result


def fleet_status(vehicle: dict, confidence_min: float) -> dict:
    """Статус машины для сводки парка (задача B3): норма, требует внимания, карантин."""
    sessions = vehicle.get("sessions", [])
    if not sessions:
        return {"fleet_status": "ok", "needs_recheck": False, "priority": None}
    last = sessions[-1]
    needs_recheck = last["status"] == "check_failed" or last.get("signal_quality") == "bad"
    decisive_index = next(
        (i for i in range(len(sessions) - 1, -1, -1) if sessions[i]["status"] != "check_failed"), None
    )
    status, priority = "ok", None
    if decisive_index is not None:
        decisive = sessions[decisive_index]
        if decisive["status"] == "anomaly":
            a = assess(decisive, vehicle, sessions[:decisive_index], confidence_min)
            priority = a["priority"]
            status = "quarantine" if priority == "high" else "attention"
            # Результат не подходит двигателю: это ошибка модели, нужна повторная проверка.
            needs_recheck = needs_recheck or a["flags"]["engine_mismatch"]
    if needs_recheck and status == "ok":
        status = "attention"
    return {"fleet_status": status, "needs_recheck": needs_recheck, "priority": priority}
