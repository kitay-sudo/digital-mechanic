"""Быстрая проверка стенда так, как его проверил бы автоматический инструмент жюри.

    python -m eval.smoke [--web URL] [--api URL] [--key КЛЮЧ_API]

Модель не вызывается, стоимость нулевая, прогон занимает секунды. Проверяет:
- страница открывается, у неё есть заголовок, язык и разметка для телефона;
- сервер жив, ML-сервис, ТОиР и база руководств подключены;
- парк и каждая машина открываются, страница руководства отдаётся картинкой;
- ошибки ввода отвечают понятным кодом и текстом по-русски, без трассировки стека;
- документация API и API для внешних систем на месте, без ключа закрыты;
- выгрузка расчёта стоимости отдаёт xlsx;
- время ответа каждого адреса.

«обязательно» — то, без чего стенд нельзя показывать. «сведения» — что стоит знать, но не ломает показ.
--web — адрес интерфейса (запросы к API идут через его прокси, как у пользователя).
--api — адрес сервера напрямую, если нужно проверить его отдельно от интерфейса.
"""
from __future__ import annotations

import argparse
import re
import sys
import time

import httpx

SLOW_SECONDS = 2.0
_CYR = re.compile(r"[а-яё]", re.IGNORECASE)
_TRACE = ("Traceback", 'File "', "sqlite3.", "pydantic_core")


class Smoke:
    def __init__(self, base: str, key: str | None):
        self.http = httpx.Client(base_url=base.rstrip("/"), timeout=30, follow_redirects=True)
        self.key = key
        self.rows: list[dict] = []

    def req(self, method: str, url: str, **kw) -> tuple[httpx.Response | None, float]:
        started = time.monotonic()
        try:
            r = self.http.request(method, url, **kw)
        except httpx.HTTPError:
            return None, time.monotonic() - started
        return r, time.monotonic() - started

    def check(self, kind: str, name: str, ok: bool, detail: str = "", seconds: float | None = None) -> bool:
        slow = seconds is not None and seconds > SLOW_SECONDS
        self.rows.append({"kind": kind, "name": name, "ok": bool(ok), "slow": slow})
        mark = "ok  " if ok else ("ОШИБКА" if kind == "обязательно" else "слабо ")
        timing = f" {seconds:.2f} с" if seconds is not None else ""
        if slow:
            timing += " (медленно)"
        print(f"   {mark} [{kind}] {name}{timing}" + (f" — {detail[:220]}" if detail and not ok else ""), flush=True)
        return bool(ok)

    def section(self, title: str) -> None:
        print(f"\n== {title}", flush=True)


def clean_error(r: httpx.Response) -> tuple[bool, str]:
    """Ошибка понятна человеку: текст по-русски, без трассировки стека и внутренних имён."""
    text = r.text
    return _CYR.search(text) is not None and not any(t in text for t in _TRACE), text[:200]


def run(s: Smoke, web: bool) -> None:
    if web:
        s.section("Интерфейс")
        r, t = s.req("GET", "/")
        ok = r is not None and r.status_code == 200
        s.check("обязательно", "главная страница открывается", ok, "" if ok else f"{getattr(r, 'status_code', 'нет связи')}", t)
        html = r.text if ok else ""
        s.check("сведения", "у страницы есть заголовок", "<title>" in html and "</title>" in html)
        s.check("сведения", "язык страницы русский (lang=ru)", 'lang="ru"' in html)
        s.check("сведения", "разметка для телефона (viewport)", 'name="viewport"' in html)
        for path in ("/log", "/v/НЕТ-ТАКОЙ"):
            r, t = s.req("GET", path)
            s.check("сведения", f"страница {path} отвечает без ошибки сервера", r is not None and r.status_code < 500,
                    str(getattr(r, "status_code", "")), t)

    s.section("Сервер и подключения")
    r, t = s.req("GET", "/api/health")
    health = r.json() if r is not None and r.status_code == 200 else {}
    s.check("обязательно", "сервер отвечает /api/health", health.get("status") == "ok", str(health)[:200], t)
    s.check("обязательно", "ML-сервис диагностики подключён", bool(health.get("ml")))
    s.check("обязательно", "ТОиР подключён", bool(health.get("toir")))
    kb = health.get("kb") or {}
    s.check("обязательно", "база руководств загружена", (kb.get("manuals") or 0) > 0 and (kb.get("chunks") or 0) > 0, str(kb))
    llm = health.get("llm") or {}
    s.check("сведения", f"модель: {llm.get('provider')} {llm.get('model')}", llm.get("provider") not in (None, "mock"), str(llm))
    r, t = s.req("GET", "/api/config")
    s.check("обязательно", "настройки интерфейса /api/config", r is not None and r.status_code == 200, "", t)

    s.section("Парк и машины")
    r, t = s.req("GET", "/api/fleet")
    fleet = r.json() if r is not None and r.status_code == 200 else {}
    vehicles = fleet.get("vehicles") or []
    s.check("обязательно", f"парк открывается, машин: {len(vehicles)}", bool(vehicles), "", t)
    worst, slowest = 0.0, ""
    broken: list[str] = []
    manual_page = None
    for v in vehicles:
        r, t = s.req("GET", f"/api/vehicles/{v['vehicle_id']}")
        if t > worst:
            worst, slowest = t, v["vehicle_id"]
        if r is None or r.status_code != 200:
            broken.append(v["vehicle_id"])
            continue
        detail = r.json()
        if manual_page is None and detail.get("manuals"):
            manual_page = detail["manuals"][0]["manual_id"]
    s.check("обязательно", "каждая машина открывается", not broken, ", ".join(broken))
    if vehicles:
        s.check("сведения", f"самая медленная карточка машины {slowest}", worst <= SLOW_SECONDS, "", worst)
    if manual_page:
        r, t = s.req("GET", f"/api/manuals/{manual_page}/pages/1/image")
        ok = r is not None and r.status_code == 200 and r.headers.get("content-type", "").startswith("image/")
        s.check("обязательно", "страница руководства отдаётся картинкой", ok, str(getattr(r, "status_code", "")), t)
        r, t = s.req("GET", f"/api/manuals/{manual_page}/pages/1")
        s.check("сведения", "текст страницы руководства", r is not None and r.status_code == 200, "", t)

    s.section("Ошибки ввода")
    r, t = s.req("GET", "/api/vehicles/НЕТ-ТАКОЙ")
    ok = r is not None and r.status_code == 404
    s.check("обязательно", "несуществующая машина: 404", ok, str(getattr(r, "status_code", "")), t)
    if r is not None:
        good, text = clean_error(r)
        s.check("сведения", "текст ошибки по-русски, без трассировки", good, text)
    r, t = s.req("POST", "/api/chat", json={})
    s.check("обязательно", "пустой запрос в чат: 422, а не 500", r is not None and r.status_code == 422,
            str(getattr(r, "status_code", "")), t)
    if r is not None:
        s.check("сведения", "ответ на неверный запрос без трассировки", not any(x in r.text for x in _TRACE), r.text[:200])
    r, t = s.req("POST", "/api/chat", json={"vehicle_id": "НЕТ-ТАКОЙ", "session_id": None, "text": "проверка"})
    s.check("обязательно", "чат по несуществующей машине: 404", r is not None and r.status_code == 404,
            str(getattr(r, "status_code", "")), t)
    r, t = s.req("POST", "/api/chat", json={"vehicle_id": vehicles[0]["vehicle_id"] if vehicles else "X",
                                           "session_id": None, "text": "я" * 5000})
    s.check("обязательно", "слишком длинный вопрос отклоняется: 422", r is not None and r.status_code == 422,
            str(getattr(r, "status_code", "")), t)
    r, t = s.req("GET", "/api/uploads/..%2F..%2Fetc%2Fpasswd")
    s.check("обязательно", "путь к чужому файлу через /api/uploads не открывается", r is not None and r.status_code in (400, 404, 422),
            str(getattr(r, "status_code", "")), t)
    r, t = s.req("GET", "/api/manuals/../pages/1/image")
    s.check("сведения", "неверный документ руководства не роняет сервер", r is not None and r.status_code < 500,
            str(getattr(r, "status_code", "")), t)

    s.section("Документация и API для внешних систем")
    r, t = s.req("GET", "/api/openapi.json")
    spec = r.json() if r is not None and r.status_code == 200 else {}
    paths = spec.get("paths") or {}
    s.check("обязательно", f"описание API OpenAPI, адресов: {len(paths)}", bool(paths), str(getattr(r, "status_code", "")), t)
    r, t = s.req("GET", "/api/docs")
    s.check("обязательно", "страница документации /api/docs", r is not None and r.status_code == 200, str(getattr(r, "status_code", "")), t)
    v1 = sorted(p for p in paths if p.startswith("/api/v1/"))
    s.check("сведения", f"методов /api/v1: {len(v1)}", bool(v1), "")
    if v1:
        r, t = s.req("GET", "/api/v1/vehicles")
        s.check("обязательно", "без ключа API для внешних систем закрыт", r is not None and r.status_code in (401, 403, 503),
                str(getattr(r, "status_code", "")), t)
        if s.key:
            r, t = s.req("GET", "/api/v1/vehicles", headers={"X-API-Key": s.key})
            s.check("обязательно", "с ключом список машин открывается", r is not None and r.status_code == 200,
                    str(getattr(r, "status_code", "")), t)
            r, t = s.req("GET", "/api/v1/vehicles", headers={"X-API-Key": s.key + "x"})
            s.check("обязательно", "с неверным ключом закрыт", r is not None and r.status_code in (401, 403),
                    str(getattr(r, "status_code", "")), t)

    s.section("Администратор и стоимость")
    r, t = s.req("GET", "/api/audit")
    code = getattr(r, "status_code", None)
    s.check("сведения", "журнал без входа администратора закрыт", code in (401, 403), f"код {code}: журнал открыт без входа", t)
    r, t = s.req("GET", "/api/usage/export.xlsx")
    code = getattr(r, "status_code", None)
    ok = r is not None and code == 200 and "spreadsheet" in r.headers.get("content-type", "")
    if code in (401, 403):
        s.check("сведения", "выгрузка расчёта стоимости закрыта входом администратора", True, "", t)
    else:
        s.check("обязательно", "выгрузка расчёта стоимости отдаёт xlsx", ok, f"код {code}", t)
    r, t = s.req("GET", "/api/usage/summary")
    s.check("сведения", "сводка расходов", r is not None and r.status_code in (200, 401, 403), str(code), t)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--web", default="http://127.0.0.1:3210", help="адрес интерфейса")
    parser.add_argument("--api", default=None, help="адрес сервера напрямую (по умолчанию — через интерфейс)")
    parser.add_argument("--key", default=None, help="ключ API для внешних систем, если он задан на стенде")
    args = parser.parse_args()

    smoke = Smoke(args.api or args.web, args.key)
    print(f"Проверяю {args.api or args.web}")
    run(smoke, web=args.api is None)
    must = [r for r in smoke.rows if r["kind"] == "обязательно"]
    failed = [r for r in must if not r["ok"]]
    weak = [r for r in smoke.rows if r["kind"] == "сведения" and not r["ok"]]
    slow = [r for r in smoke.rows if r["slow"]]
    print(f"\nИтог: обязательных {len(must) - len(failed)} из {len(must)}, слабых мест {len(weak)}, медленных ответов {len(slow)}")
    for r in failed:
        print(f"   ОШИБКА: {r['name']}")
    for r in weak:
        print(f"   слабо: {r['name']}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
