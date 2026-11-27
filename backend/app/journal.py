"""Журнал обращений для администратора: все ответы агента и вопросы механиков администратору.

Журнал отдаётся постранично с сервера, с фильтрами по датам, машине, механику, типу случая,
статусу разбора и поиском по тексту вопроса и ответа.

Случай — строка журнала, которую администратор должен разобрать: в руководстве нет ответа,
руководства не загружены, ошибка диагностики, сообщение механика, посторонний текст в данных
диагностики. У случая статус «новый / в работе / разобрано», комментарий к решению, кто и когда
изменил, и история изменений. Новое сообщение механика по уже разобранному ответу возвращает
случай в работу.

Повторы склеиваются в одну строку «повторилось N раз»: одинаковые вопросы без ответа по одной
модели двигателя (текст нормализуется: регистр, пробелы, знаки) и повторные сообщения механиков
на один ответ. Разбор отмечает всю группу. Новый повтор после разбора возвращает группу в работу.

Для фильтров у каждого ответа агента есть строка в journal_items: вопрос, автор, тип случая,
ключ группы. Индекс дописывается при чтении журнала, поэтому запись ответа его не ждёт.
"""
from __future__ import annotations

import json
import os
import re
import uuid
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from . import alerts, fleet

# Сменился способ разбора ответа на поля журнала — индекс строится заново из сообщений
VERSION = "1"

SCHEMA = """
CREATE TABLE IF NOT EXISTS journal_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS journal_items (
    item_id TEXT PRIMARY KEY,
    message_id INTEGER, admin_id INTEGER,
    vehicle_id TEXT, engine_model TEXT, session_id TEXT,
    ts REAL NOT NULL, created_at TEXT NOT NULL,
    author TEXT, question TEXT NOT NULL, answer TEXT NOT NULL, photos INTEGER NOT NULL DEFAULT 0,
    kind TEXT, gap_type TEXT, injection INTEGER NOT NULL DEFAULT 0,
    group_key TEXT, search TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS journal_items_ts ON journal_items(ts);
CREATE INDEX IF NOT EXISTS journal_items_message ON journal_items(message_id);
CREATE TABLE IF NOT EXISTS admin_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    vehicle_id TEXT, text TEXT NOT NULL, author TEXT, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS case_status (
    item_id TEXT PRIMARY KEY, status TEXT NOT NULL, comment TEXT NOT NULL DEFAULT '',
    reviewer TEXT, updated_at TEXT NOT NULL, report_seen INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS case_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id TEXT NOT NULL, batch TEXT NOT NULL, status TEXT NOT NULL,
    comment TEXT NOT NULL DEFAULT '', reviewer TEXT, created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS case_history_item ON case_history(item_id);
CREATE INDEX IF NOT EXISTS reports_message ON reports(message_id);
"""

STATUSES = ("new", "in_work", "reviewed")
STATUS_LABELS = {"new": "Новый", "in_work": "В работе", "reviewed": "Разобрано"}
_RANK = {"new": 0, "in_work": 1, "reviewed": 2}
_BY_RANK = {v: k for k, v in _RANK.items()}
# Фильтр статуса: open — «Требуют внимания» (новые и в работе), all — весь журнал
STATUS_FILTERS = {"open": (0, 1), "new": (0,), "in_work": (1,), "reviewed": (2,), "cases": (0, 1, 2)}
TYPES = tuple(alerts.LABELS)
MAX_PAGE_SIZE = 100


# --- время ---
def local_tz():
    """Местное время автопарка (APP_TZ, по умолчанию московское), а не время сервера: в контейнере оно UTC."""
    try:
        return ZoneInfo(os.environ.get("APP_TZ", "Europe/Moscow"))
    except Exception:  # в образе может не быть базы часовых поясов
        return timezone(timedelta(hours=3))


def now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def ts_of(iso: str | None) -> float:
    if not iso:
        return 0.0
    try:
        moment = datetime.fromisoformat(iso)
    except ValueError:
        return 0.0
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=local_tz())
    return moment.timestamp()


def _bound(value: str | None, end: bool) -> datetime | None:
    """Граница периода. Дата без времени — сутки по местному времени, конец периода включает эту дату."""
    if not value or not value.strip():
        return None
    value = value.strip()
    tz = local_tz()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        day = date.fromisoformat(value)
        return datetime.combine(day + timedelta(days=1) if end else day, time(0), tz)
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"Неверная дата: {value}. Нужен вид 2026-11-27 или 2026-11-27T08:00") from exc
    return moment if moment.tzinfo else moment.replace(tzinfo=tz)


def period(start: str | None, end: str | None, default_today: bool = False) -> tuple[datetime | None, datetime | None]:
    """Период с/по. default_today: без границ — сегодня по местному времени."""
    lo, hi = _bound(start, False), _bound(end, True)
    if default_today and lo is None and hi is None:
        today = datetime.now(local_tz()).date()
        lo = datetime.combine(today, time(0), local_tz())
        hi = lo + timedelta(days=1)
    if lo and hi and hi <= lo:
        raise ValueError("Конец периода раньше начала")
    return lo, hi


# --- таблицы ---
def _fold(text: str | None) -> str | None:
    return text.casefold().replace("ё", "е") if text else text


def init(store) -> None:
    """Таблицы журнала и перенос старых отметок «Разобрано». Вызывается при открытии хранилища."""
    db = store._db
    # Поиск без учёта регистра по-русски: встроенный lower() в SQLite понимает только латиницу
    db.create_function("casefold", 1, _fold, deterministic=True)
    with store._lock:
        db.executescript(SCHEMA)
        version = db.execute("SELECT value FROM journal_meta WHERE key='version'").fetchone()
        if not version or version[0] != VERSION:
            db.execute("DELETE FROM journal_items")
            db.execute("INSERT OR REPLACE INTO journal_meta (key, value) VALUES ('version', ?)", (VERSION,))
        if not db.execute("SELECT 1 FROM journal_meta WHERE key='reviews_moved'").fetchone():
            # Старая отметка «Разобрано» (таблица reviews) становится статусом с записью в истории
            for r in db.execute("SELECT message_id, reviewed_at FROM reviews").fetchall():
                item = f"m_{r['message_id']}"
                seen = db.execute("SELECT COALESCE(MAX(id), 0) FROM reports WHERE message_id=?",
                                  (r["message_id"],)).fetchone()[0]
                db.execute("INSERT OR IGNORE INTO case_status (item_id, status, comment, reviewer, updated_at, "
                           "report_seen) VALUES (?, 'reviewed', '', NULL, ?, ?)", (item, r["reviewed_at"], seen))
                db.execute("INSERT INTO case_history (item_id, batch, status, comment, reviewer, created_at) "
                           "VALUES (?, ?, 'reviewed', '', NULL, ?)", (item, f"old-{item}", r["reviewed_at"]))
            db.execute("INSERT OR REPLACE INTO journal_meta (key, value) VALUES ('reviews_moved', '1')")
        db.commit()


def meta(store, key: str) -> str | None:
    rows = store._all("SELECT value FROM journal_meta WHERE key=?", (key,))
    return rows[0]["value"] if rows else None


def set_meta(store, key: str, value: str) -> None:
    store._exec("INSERT OR REPLACE INTO journal_meta (key, value) VALUES (?, ?)", (key, value))


# --- индекс журнала ---
def normalize(text: str) -> str:
    """Текст вопроса для склейки повторов: без регистра, лишних пробелов и знаков."""
    text = _fold(text or "") or ""
    text = re.sub(r"[^\w\s]|_", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _answer_row(r) -> tuple:
    payload = json.loads(r["payload"])
    asked = json.loads(r["asked"]) if r["asked"] else {}
    vehicle = fleet.get_vehicle(r["vehicle_id"]) or {}
    engine = vehicle.get("engine_model") or ""
    question = (asked.get("text") or "").strip()
    answer = (payload.get("text") or "").strip()
    gap = alerts.gap_of(payload)
    gap_type = gap["type"] if gap else None
    kind = payload.get("kind")
    diagnosis = payload.get("diagnosis") or {}
    flagged = int(kind == "verdict" and bool(diagnosis.get("description_flagged")))
    group = None
    if gap_type == "no_answer":
        # Вердикт без инструкции склеивается по типу неисправности: вопрос у таких проверок одинаковый
        if kind == "verdict":
            group = f"g:{engine}:verdict:{diagnosis.get('anomaly_type') or ''}"
        elif normalize(question):
            group = f"g:{engine}:{normalize(question)}"
    return (f"m_{r['id']}", r["id"], None, r["vehicle_id"], engine, r["session_id"], ts_of(r["created_at"]),
            r["created_at"], asked.get("author"), question, answer, len(asked.get("images") or []), kind, gap_type,
            flagged, group, _fold(f"{question}\n{answer}") or "")


def _admin_row(r) -> tuple:
    vehicle = fleet.get_vehicle(r["vehicle_id"]) if r["vehicle_id"] else None
    return (f"a_{r['id']}", None, r["id"], r["vehicle_id"], (vehicle or {}).get("engine_model"), None,
            ts_of(r["created_at"]), r["created_at"], r["author"], r["text"], "", 0, "admin", "report", 0, None,
            _fold(r["text"]) or "")


def sync(store) -> None:
    """Дописывает в индекс новые ответы агента и вопросы администратору, убирает ответы очищенных чатов."""
    last = store._all("SELECT COALESCE(MAX(message_id), 0) AS n, COALESCE(MAX(admin_id), 0) AS a FROM journal_items")[0]
    # Вопрос к ответу — последнее сообщение механика по этой машине перед ответом. Одним запросом, без N+1
    answers = store._all(
        "SELECT a.id, a.vehicle_id, a.session_id, a.payload, a.created_at, "
        "(SELECT u.payload FROM messages u WHERE u.vehicle_id=a.vehicle_id AND u.role='user' AND u.id<a.id "
        "ORDER BY u.id DESC LIMIT 1) AS asked "
        "FROM messages a WHERE a.role='assistant' AND a.id>? ORDER BY a.id", (last["n"],))
    admin = store._all("SELECT * FROM admin_messages WHERE id>? ORDER BY id", (last["a"],))
    rows = [_answer_row(r) for r in answers] + [_admin_row(r) for r in admin]
    orphans = "FROM journal_items WHERE message_id IS NOT NULL AND message_id NOT IN (SELECT id FROM messages)"
    stale = bool(store._all(f"SELECT 1 {orphans} LIMIT 1"))
    if not rows and not stale:
        return
    with store._lock:
        if rows:
            store._db.executemany(
                "INSERT OR IGNORE INTO journal_items (item_id, message_id, admin_id, vehicle_id, engine_model, "
                "session_id, ts, created_at, author, question, answer, photos, kind, gap_type, injection, group_key, "
                "search) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
        if stale:
            store._db.execute(f"DELETE {orphans}")
        store._db.commit()


# --- выборка: фильтры, статус и склейка в одном запросе ---
_BASE = """
WITH rep AS (SELECT message_id, COUNT(*) AS n, MAX(id) AS last_id FROM reports GROUP BY message_id),
base AS (
  SELECT j.item_id, j.rowid AS rid, j.ts, j.injection, j.message_id,
    CASE WHEN rep.n > 0 THEN 'report' ELSE j.gap_type END AS type,
    CASE WHEN rep.n > 0 THEN j.item_id ELSE COALESCE(j.group_key, j.item_id) END AS gkey,
    CASE
      WHEN rep.n IS NULL AND j.gap_type IS NULL THEN NULL
      WHEN s.status IS NULL OR COALESCE(rep.last_id, 0) > s.report_seen THEN 0
      WHEN s.status = 'in_work' THEN 1
      WHEN s.status = 'reviewed' THEN 2
      ELSE 0 END AS srank
  FROM journal_items j
  LEFT JOIN rep ON rep.message_id = j.message_id
  LEFT JOIN case_status s ON s.item_id = j.item_id
  WHERE {where}
),
picked AS (SELECT * FROM base WHERE {type_where}),
grouped AS (
  SELECT item_id, rid, ts, gkey, type,
    ROW_NUMBER() OVER (PARTITION BY gkey ORDER BY ts DESC, rid DESC) AS rn,
    COUNT(*) OVER (PARTITION BY gkey) AS n,
    MIN(srank) OVER (PARTITION BY gkey) AS grank,
    MAX(injection) OVER (PARTITION BY gkey) AS inj
  FROM picked
)
"""


def _like(text: str) -> str:
    return "%" + re.sub(r"([\\%_])", r"\\\1", _fold(text) or "") + "%"


def _where(f: dict) -> tuple[str, list, str, list]:
    where, args = ["1=1"], []
    if f.get("from_ts") is not None:
        where.append("j.ts >= ?")
        args.append(f["from_ts"])
    if f.get("to_ts") is not None:
        where.append("j.ts < ?")
        args.append(f["to_ts"])
    if f.get("vehicle_id"):
        where.append("j.vehicle_id = ?")
        args.append(f["vehicle_id"])
    if f.get("mechanic"):
        # Механик — автор вопроса или сообщения о проблеме с ответом
        where.append("(casefold(j.author) = ? OR EXISTS (SELECT 1 FROM reports r WHERE r.message_id = j.message_id "
                     "AND casefold(r.author) = ?))")
        args += [_fold(f["mechanic"].strip())] * 2
    if f.get("q") and f["q"].strip():
        pattern = _like(f["q"].strip())
        where.append("(j.search LIKE ? ESCAPE '\\' OR EXISTS (SELECT 1 FROM reports r WHERE r.message_id = j.message_id "
                     "AND casefold(r.reason || ' ' || r.text) LIKE ? ESCAPE '\\'))")
        args += [pattern, pattern]
    if f.get("item_ids") is not None:
        where.append(f"j.item_id IN ({','.join('?' * len(f['item_ids'])) or 'NULL'})")
        args += list(f["item_ids"])
    type_where, type_args = "1=1", []
    if f.get("type") == "injection":
        type_where = "(type = 'injection' OR injection = 1)"
    elif f.get("type"):
        type_where = "type = ?"
        type_args = [f["type"]]
    return " AND ".join(where), args, type_where, type_args


def _status_where(status: str | None) -> str:
    ranks = STATUS_FILTERS.get(status or "all")
    return f" AND grank IN ({','.join(map(str, ranks))})" if ranks else ""


def _groups(store, f: dict, status: str | None, limit: int | None = None, offset: int = 0) -> list:
    where, args, type_where, type_args = _where(f)
    sql = _BASE.format(where=where, type_where=type_where) + (
        "SELECT item_id, gkey, n, grank, inj, type FROM grouped WHERE rn = 1" + _status_where(status) +
        " ORDER BY ts DESC, rid DESC")
    extra: list = []
    if limit is not None:
        sql += " LIMIT ? OFFSET ?"
        extra = [limit, offset]
    return store._all(sql, tuple(args + type_args + extra))


def _count(store, f: dict, status: str | None) -> int:
    where, args, type_where, type_args = _where(f)
    sql = _BASE.format(where=where, type_where=type_where) + (
        "SELECT COUNT(*) AS n FROM grouped WHERE rn = 1" + _status_where(status))
    return store._all(sql, tuple(args + type_args))[0]["n"]


def _members(store, gkeys: list[str]) -> list:
    """Все строки групп целиком, без фильтров: разбор отмечает всю группу."""
    if not gkeys:
        return []
    sql = _BASE.format(where="1=1", type_where="1=1") + (
        f"SELECT item_id, gkey, ts, message_id FROM base WHERE gkey IN ({','.join('?' * len(gkeys))}) "
        "ORDER BY ts DESC, rid DESC")
    return store._all(sql, tuple(gkeys))


def _gkey_of(store, item_ids: list[str]) -> dict[str, str]:
    if not item_ids:
        return {}
    sql = _BASE.format(where=f"j.item_id IN ({','.join('?' * len(item_ids))})", type_where="1=1") + (
        "SELECT item_id, gkey FROM base")
    return {r["item_id"]: r["gkey"] for r in store._all(sql, tuple(item_ids))}


# --- строки журнала ---
def sources_of(payload: dict) -> list[dict]:
    answer = payload.get("answer") or {}
    draft = payload.get("draft") or {}
    items = [*(answer.get("checks") or []), *(answer.get("repair") or []),
             *(draft.get("operations") or []), *(draft.get("spare_parts") or [])]
    items += [{"refs": [s["ref"]]} for block in answer.get("conflicts") or [] for s in block.get("statements", [])]
    out, seen = [], set()
    for item in items:
        for ref in item.get("refs", []):
            key = (ref["manual_id"], ref["pdf_page"])
            if key not in seen:
                seen.add(key)
                out.append({"manual_id": ref["manual_id"], "short": ref["short"], "pdf_page": ref["pdf_page"]})
    return out


def _in(ids: list) -> str:
    return ",".join("?" * len(ids)) or "NULL"


def _items(store, groups: list) -> list[dict]:
    """Строки журнала по группам: поля последнего повтора, число повторов, статус группы."""
    ids = [g["item_id"] for g in groups]
    if not ids:
        return []
    rows = {r["item_id"]: r for r in store._all(f"SELECT * FROM journal_items WHERE item_id IN ({_in(ids)})", tuple(ids))}
    message_ids = [r["message_id"] for r in rows.values() if r["message_id"]]
    payloads = {r["id"]: json.loads(r["payload"]) for r in store._all(
        f"SELECT id, payload FROM messages WHERE id IN ({_in(message_ids)})", tuple(message_ids))}
    reports: dict[int, list[dict]] = {}
    for r in store._all(f"SELECT * FROM reports WHERE message_id IN ({_in(message_ids)}) ORDER BY id", tuple(message_ids)):
        reports.setdefault(r["message_id"], []).append(
            {"reason": r["reason"], "text": r["text"], "author": r["author"], "created_at": r["created_at"]})
    statuses = {r["item_id"]: r for r in store._all(
        f"SELECT * FROM case_status WHERE item_id IN ({_in(ids)})", tuple(ids))}
    out = []
    for g in groups:
        r = rows.get(g["item_id"])
        if r is None:
            continue
        payload = payloads.get(r["message_id"], {}) if r["message_id"] else {}
        reps = reports.get(r["message_id"], []) if r["message_id"] else []
        vehicle = fleet.get_vehicle(r["vehicle_id"]) if r["vehicle_id"] else None
        status = _BY_RANK.get(g["grank"]) if g["grank"] is not None else None
        st = statuses.get(r["item_id"])
        gap = None
        if g["type"]:
            gap = {"type": g["type"], "label": alerts.LABELS[g["type"]], "title": alerts.TITLES[g["type"]],
                   "status": status, "status_label": STATUS_LABELS.get(status or ""),
                   # Совместимость со старым интерфейсом: время отметки «Разобрано»
                   "reviewed_at": st["updated_at"] if st and status == "reviewed" else None}
            if g["type"] == "report" and reps:
                gap["title"] = f"{alerts.TITLES['report']}: {reps[-1]['reason']}"
            elif r["kind"] == "admin":
                gap["title"] = "Вопрос механика администратору"
        out.append({
            "id": r["item_id"], "source": "admin" if r["kind"] == "admin" else "answer",
            "created_at": r["created_at"], "vehicle_id": r["vehicle_id"],
            "vehicle_title": (fleet.title_of(vehicle) if vehicle else r["vehicle_id"]) or "",
            "engine_model": r["engine_model"], "session_id": r["session_id"],
            "question": r["question"], "author": r["author"], "photos": r["photos"],
            "kind": r["kind"], "answer": r["answer"],
            "sources": sources_of(payload), "tools": [s.get("tool") for s in payload.get("steps", [])],
            "ticket_id": (payload.get("ticket") or {}).get("ticket_id"), "usage": payload.get("usage") or None,
            "report": reps[-1] if reps else None, "reports_count": len(reps),
            # Повторилось N раз: одинаковые вопросы без ответа или сообщения механиков на этот ответ
            "gap": gap, "status": status, "repeats": len(reps) if g["type"] == "report" and reps else g["n"],
            "injection": bool(g["inj"]),
        })
    return out


def page(store, filters: dict | None = None, status: str | None = None, page_no: int = 1,
         page_size: int = 20) -> dict:
    """Страница журнала: строки (группы повторов), сколько всего, номер и размер страницы."""
    sync(store)
    f = filters or {}
    size = max(1, min(MAX_PAGE_SIZE, page_size))
    total = _count(store, f, status)
    pages = max(1, -(-total // size))
    page_no = max(1, min(page_no, pages))
    groups = _groups(store, f, status, size, (page_no - 1) * size)
    return {"items": _items(store, groups), "total": total, "page": page_no, "page_size": size}


def open_count(store, filters: dict | None = None) -> int:
    """Сколько случаев «новый» и «в работе» (группы повторов считаются одним): число у пункта «Журнал»."""
    sync(store)
    return _count(store, filters or {}, "open")


def facets(store) -> dict:
    """Чем можно отфильтровать журнал: машины и механики, которые в нём есть."""
    vehicles = [r["vehicle_id"] for r in store._all(
        "SELECT DISTINCT vehicle_id FROM journal_items WHERE vehicle_id IS NOT NULL ORDER BY vehicle_id")]
    names = {r["author"] for r in store._all("SELECT DISTINCT author FROM journal_items WHERE author IS NOT NULL")}
    names |= {r["author"] for r in store._all("SELECT DISTINCT author FROM reports WHERE author IS NOT NULL")}
    titled = []
    for vehicle_id in vehicles:
        vehicle = fleet.get_vehicle(vehicle_id)
        titled.append({"vehicle_id": vehicle_id, "title": fleet.title_of(vehicle) if vehicle else vehicle_id})
    return {"vehicles": titled, "mechanics": sorted(n for n in names if n.strip())}


# --- карточка случая ---
def _history(store, item_ids: list[str]) -> list[dict]:
    """История группы: одно изменение отмечает всю группу, поэтому записи склеены по действию."""
    rows = store._all(
        f"SELECT batch, status, comment, reviewer, MIN(created_at) AS at, COUNT(*) AS n, MIN(id) AS first "
        f"FROM case_history WHERE item_id IN ({_in(item_ids)}) GROUP BY batch ORDER BY first", tuple(item_ids))
    return [{"status": r["status"], "status_label": STATUS_LABELS.get(r["status"], r["status"]),
             "comment": r["comment"], "reviewer": r["reviewer"], "at": r["at"]} for r in rows]


def case(store, item_id: str) -> dict | None:
    """Карточка случая: полный вопрос, ответ агента, источники, сообщения механика, повторы, история."""
    sync(store)
    gkey = _gkey_of(store, [item_id]).get(item_id)
    if gkey is None:
        return None
    members = _members(store, [gkey])
    member_ids = [m["item_id"] for m in members]
    group = _groups(store, {"item_ids": member_ids}, None)
    head = next((g for g in group if g["gkey"] == gkey), None)
    if head is None:
        return None
    # Карточка показывает выбранную строку, а число повторов и статус — по всей группе
    chosen = dict(zip(head.keys(), head))
    chosen["item_id"] = item_id
    item = _items(store, [chosen])[0]
    row = store._all("SELECT * FROM journal_items WHERE item_id=?", (item_id,))[0]
    payload = {}
    reports: list[dict] = []
    if row["message_id"]:
        found = store._all("SELECT payload FROM messages WHERE id=?", (row["message_id"],))
        payload = json.loads(found[0]["payload"]) if found else {}
        reports = [{"reason": r["reason"], "text": r["text"], "author": r["author"], "created_at": r["created_at"]}
                   for r in store._all("SELECT * FROM reports WHERE message_id=? ORDER BY id", (row["message_id"],))]
    answer = payload.get("answer") or {}
    assessment = payload.get("assessment") or {}
    item["details"] = {
        "summary": answer.get("summary") or "",
        "checks": [c.get("text", "") for c in answer.get("checks") or []],
        "repair": [c.get("text", "") for c in answer.get("repair") or []],
        "limitations": list(answer.get("limitations") or []),
        "recommendation_text": answer.get("recommendation_text"),
        "warnings": list(assessment.get("warnings") or []),
        "anomaly_title": (payload.get("diagnosis") or {}).get("anomaly_title"),
    }
    item["reports"] = reports
    occurrences = store._all(f"SELECT item_id, created_at, vehicle_id, author FROM journal_items "
                             f"WHERE item_id IN ({_in(member_ids)}) ORDER BY ts DESC, rowid DESC", tuple(member_ids))
    item["occurrences"] = [{"id": o["item_id"], "created_at": o["created_at"], "vehicle_id": o["vehicle_id"],
                            "author": o["author"]} for o in occurrences]
    item["history"] = _history(store, member_ids)
    latest = store._all(f"SELECT * FROM case_status WHERE item_id IN ({_in(member_ids)}) "
                        f"ORDER BY updated_at DESC LIMIT 1", tuple(member_ids))
    item["comment"] = latest[0]["comment"] if latest else ""
    item["reviewer"] = latest[0]["reviewer"] if latest else None
    item["updated_at"] = latest[0]["updated_at"] if latest else None
    return item


# --- разбор ---
def set_status(store, item_ids: list[str], status: str, comment: str | None = None,
               reviewer: str | None = None) -> dict:
    """Меняет статус случаев. Отмечается вся группа повторов. comment None — комментарий прежний."""
    if status not in STATUSES:
        raise ValueError(f"Неизвестный статус: {status}")
    sync(store)
    gkeys = sorted(set(_gkey_of(store, item_ids).values()))
    members = _members(store, gkeys)
    if not members:
        return {"updated": 0, "at": None}
    ids = [m["item_id"] for m in members]
    message_ids = [m["message_id"] for m in members if m["message_id"]]
    seen = {r["message_id"]: r["n"] for r in store._all(
        f"SELECT message_id, MAX(id) AS n FROM reports WHERE message_id IN ({_in(message_ids)}) GROUP BY message_id",
        tuple(message_ids))}
    current = {r["item_id"]: r["comment"] for r in store._all(
        f"SELECT item_id, comment FROM case_status WHERE item_id IN ({_in(ids)})", tuple(ids))}
    stamp, batch = now(), uuid.uuid4().hex[:16]
    reviewer = (reviewer or "").strip() or None
    with store._lock:
        for m in members:
            text = current.get(m["item_id"], "") if comment is None else comment.strip()
            store._db.execute(
                "INSERT OR REPLACE INTO case_status (item_id, status, comment, reviewer, updated_at, report_seen) "
                "VALUES (?,?,?,?,?,?)", (m["item_id"], status, text, reviewer, stamp, seen.get(m["message_id"], 0)))
            store._db.execute(
                "INSERT INTO case_history (item_id, batch, status, comment, reviewer, created_at) VALUES (?,?,?,?,?,?)",
                (m["item_id"], batch, status, "" if comment is None else comment.strip(), reviewer, stamp))
        store._db.commit()
    return {"updated": len(members), "at": stamp}


def reviewed_map(store) -> dict[int, str]:
    """Ответы агента со статусом «разобрано» и время отметки: для старого вида журнала (store.audit)."""
    rows = store._all(
        "SELECT s.item_id, s.updated_at FROM case_status s "
        "WHERE s.status = 'reviewed' AND s.item_id LIKE 'm\\_%' ESCAPE '\\' AND s.report_seen >= "
        "(SELECT COALESCE(MAX(r.id), 0) FROM reports r WHERE r.message_id = CAST(substr(s.item_id, 3) AS INTEGER))")
    return {int(r["item_id"][2:]): r["updated_at"] for r in rows}


# --- вопрос администратору ---
def add_admin_message(store, vehicle_id: str | None, text: str, author: str | None) -> dict:
    created = now()
    cur = store._exec("INSERT INTO admin_messages (vehicle_id, text, author, created_at) VALUES (?,?,?,?)",
                      (vehicle_id, text, author, created))
    return {"id": f"a_{cur.lastrowid}", "created_at": created}
