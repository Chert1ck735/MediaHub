"""Выгрузка агрегатов через HTTP API, без доступа к базе.

Нужен, когда Postgres живёт на сервере и напрямую до него не достучаться, а
приложение при этом открывается. Скрипт логинится тем же аккаунтом, что и
браузер, и забирает те же цифры, что рисует интерфейс.

Авторов и их идентификаторы не выгружает. Тексты выгружает: примеры
комментариев по болям (pain_examples.csv) — они нужны для слайдов, это
публичные комментарии из открытых пабликов, но файл всё равно не для
пересылки куда попало.

Запуск:
    python -m tools.sigma_export_api --base-url http://192.168.177.173:8000 --email me@mail.ru
    python -m tools.sigma_export_api --base-url ... --email ... --periods week,month,year,all
    python -m tools.sigma_export_api --base-url ... --email ... --since 2025-06-01
"""
from __future__ import annotations

import argparse
import csv
import getpass
import json
import re
import sys
from pathlib import Path

import httpx

DEFAULT_PERIODS = ["week", "month", "3months", "year", "all"]
SUMMARY_FIELDS = [
    "total_comment_count",
    "classified_comment_count",
    "unclassified_comment_count",
    "relevant_comment_count",
    "appeal_count",
    "complaint_count",
    "request_count",
    "gratitude_count",
    "pain_count",
]


def login(client: httpx.Client, email: str, password: str) -> str:
    response = client.post("/api/auth/login", json={"email": email, "password": password})
    response.raise_for_status()
    return response.json()["access_token"]


def fetch(client: httpx.Client, path: str, token: str, **params):
    response = client.get(path, params=params, headers={"Authorization": f"Bearer {token}"})
    response.raise_for_status()
    return response.json()


def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter=";", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    print(f"  {path.name}: {len(rows)} строк")


def write_pain_examples(path: Path, pains: list[dict]) -> None:
    """Примеры комментариев по болям отдельной таблицей.

    В pains.csv они попадают одной ячейкой с питоновским списком внутри —
    в Excel это нечитаемо, а для слайдов нужны именно цитаты построчно.
    """
    rows = []
    for pain in pains:
        for example in pain.get("comment_examples") or []:
            rows.append({
                "pain": pain.get("title"),
                "category": pain.get("category"),
                "mentions_count": pain.get("mentions_count"),
                "text": (example.get("text") or "").replace("\n", " ").strip(),
                "message_type": example.get("message_type"),
                "sentiment": example.get("sentiment"),
                "link": example.get("link") or example.get("url"),
            })
    if rows:
        write_csv(path, rows, list(rows[0].keys()))


def write_appeals_by_month(path: Path, daily: list[dict]) -> None:
    """Помесячная кривая обращений — ответ на «это поток или разовый всплеск»."""
    months: dict[str, int] = {}
    for row in daily:
        month = str(row.get("day", ""))[:7]
        if month:
            months[month] = months.get(month, 0) + int(row.get("appeals") or 0)
    rows = [{"month": m, "appeals": months[m]} for m in sorted(months)]
    if rows:
        write_csv(path, rows, ["month", "appeals"])


def fetch_address_cases(client: httpx.Client, token: str, out: Path) -> list[dict]:
    """Сырые адресные кейсы. Ручка отдаёт XLSX, поэтому файл сохраняем как есть,
    а для статистики достаём поле case из hierarchy."""
    try:
        response = client.get(
            "/api/analytics/address-cases/export",
            params={"limit": 200_000, "only_with_case": "false"},
            headers={"Authorization": f"Bearer {token}"},
            timeout=300.0,
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        print(f"  пропущено /address-cases/export: {exc}")
        return []

    raw = out / "all_comments.xlsx"
    raw.write_bytes(response.content)
    print(f"  {raw.name}: {len(response.content) // 1024} КБ")

    try:
        import pandas as pd

        frame = pd.read_excel(raw)
    except Exception as exc:
        print(f"  XLSX не разобран ({exc}) — статистика по адресам пропущена")
        return []

    column = next(
        (c for c in ("hierarchy_case", "case", "кейс") if c in frame.columns), None
    )
    if column is not None:
        return [{"case": value} for value in frame[column].fillna("").astype(str)]

    json_column = next(
        (c for c in ("hierarchy_json", "hierarchy") if c in frame.columns), None
    )
    if json_column is None:
        print(f"  в выгрузке нет колонки с кейсом: {list(frame.columns)[:8]}")
        return []

    cases = []
    for value in frame[json_column].fillna(""):
        try:
            cases.append({"case": (json.loads(value) or {}).get("case", "")})
        except (TypeError, ValueError):
            cases.append({"case": ""})
    return cases


def write_publics_links(path: Path, publics: list[dict]) -> None:
    """Площадки построчно по ссылкам: id, регион, границы собранного периода."""
    rows = []
    for public in publics:
        for link in public.get("links") or []:
            rows.append({
                "площадка": public.get("name"),
                "public_id": public.get("id"),
                "регион": public.get("region_name"),
                "ссылка": link.get("url"),
                "external_id": link.get("external_public_id"),
                "сеть": link.get("social_network_code"),
                "публикаций": link.get("publications_count"),
                "комментариев": link.get("total_comments"),
                "подписчиков": link.get("subscribers_count"),
                "первый комментарий": link.get("first_comment_at"),
                "последний комментарий": link.get("last_comment_at"),
                "автопарсинг": link.get("autoparse_enabled"),
                "последний автопарсинг": link.get("last_autoparse_at"),
            })
    if rows:
        write_csv(path, rows, list(rows[0].keys()))


def write_data_health(path: Path, health: dict) -> None:
    """Состояния классификации по площадкам.

    Процент в интерфейсе и числа в /summary считаются по-разному: интерфейс
    берёт живые таблицы (classified / все комментарии ссылки), а summary —
    последний снапшот, куда необработанное просто не попадает. Отсюда 74% на
    экране при «нуле неклассифицированных» в выгрузке. Здесь раскладка по
    состояниям, чтобы отличить очередь от пропущенных записей.
    """
    rows = []
    for item in health.get("items") or []:
        comments = int(item.get("comments_count") or 0)
        rows.append({
            "площадка": item.get("public_name"),
            "ссылка": item.get("url"),
            "комментариев": comments,
            "done": item.get("classified_count"),
            "в очереди (pending)": item.get("pending_count"),
            "в работе (processing)": item.get("processing_count"),
            "ошибка (failed)": item.get("failed_count"),
            "без записи анализа": item.get("missing_analysis_count"),
            "классиф., %": item.get("classification_percent"),
            "статус": item.get("classification_status"),
            "последний анализ": item.get("last_analysis_at"),
        })
    if rows:
        rows.sort(key=lambda r: r["классиф., %"] if r["классиф., %"] is not None else 101)
        write_csv(path, rows, list(rows[0].keys()))


# Номер дома: после запятой, после «д./дом» или в конце строки («Гусарова 28»).
# Свободное число не годится — «4-я Дальневосточная» и «роддом 5» это не адрес дома.
HOUSE_NUMBER = re.compile(
    r"(?:,\s*(?:д\.?\s*|дом\s*)?\d{1,4}\s?[а-я]?\b"
    r"|\bд\.\s*\d{1,4}\b"
    r"|\bдом\s+\d{1,4}\b"
    r"|[А-Яа-яЁё]{3,}\s+\d{1,4}\s?[а-я]?\s*$)",
    re.I,
)
# Порядковые в названиях улиц: «4-я Дальневосточная», «2-й Луговой».
ORDINAL = re.compile(r"\d+\s*-\s*[яйеао]\b", re.I)
STREET = re.compile(
    r"\b(ул\.|ул\s|улиц|просп|пр-?кт|проспект|переул|пер\.|бульвар|шоссе|проезд|наб\.|набереж|мкр|квартал)",
    re.I,
)
# «д.» перед словом — деревня, а не дом; «с.», «пос.» — тоже населённый пункт.
SETTLEMENT_ONLY = re.compile(r"\b(район|округ|деревн|посёл|посел|город|край)\b", re.I)


def address_detail_level(case_name: str) -> str:
    """Насколько подробен адресный кейс: дом, улица или только населённый пункт.

    Эвристика по тексту, а не разбор адреса: точного парсера тут нет и не надо,
    задача — оценить порядок величины, реальна ли карта по улицам.
    """
    text = (case_name or "").strip()
    if not text:
        return "пусто"
    has_street = bool(STREET.search(text))
    has_number = bool(HOUSE_NUMBER.search(ORDINAL.sub(" ", text)))
    if has_number and (has_street or not SETTLEMENT_ONLY.search(text)):
        return "дом"
    if has_street:
        return "улица"
    return "населённый пункт"


def write_address_stats(path: Path, cases: list[dict], geo: dict) -> None:
    """Доля обращений с адресом и распределение по детализации.

    Эталон не нужен — это описательная статистика, она отвечает на вопрос
    «карта по улицам вообще реальна или нет».
    """
    levels: dict[str, int] = {}
    for case in cases:
        levels[address_detail_level(case.get("case"))] = (
            levels.get(address_detail_level(case.get("case")), 0) + 1
        )
    total = sum(levels.values()) or 1
    rows = [
        {"показатель": f"кейсов с уровнем «{level}»", "значение": count,
         "доля от кейсов, %": round(count / total * 100, 1)}
        for level, count in sorted(levels.items(), key=lambda kv: -kv[1])
    ]
    for key, title in (
        ("total_cases", "адресных кейсов всего"),
        ("geocoded_cases", "геокодировано"),
        ("not_geocoded_cases", "не геокодировано"),
        ("rejected_cases", "отклонено геокодером"),
        ("untried_cases", "не пробовали"),
        ("skipped_invalid_cases", "пропущено как невалидные"),
    ):
        if key in geo:
            rows.append({"показатель": title, "значение": geo.get(key), "доля от кейсов, %": ""})
    if rows:
        write_csv(path, rows, ["показатель", "значение", "доля от кейсов, %"])


def export(base_url: str, email: str, password: str, periods: list[str], out: Path,
           since: str) -> int:
    out.mkdir(parents=True, exist_ok=True)

    with httpx.Client(base_url=base_url.rstrip("/"), timeout=120.0) as client:
        token = login(client, email, password)
        print(f"Вход выполнен: {email}")

        summaries, categories = [], []
        for period in periods:
            data = fetch(client, "/api/analytics/summary", token, period=period)
            sla = data.get("sla") or {}
            row = {"period": period}
            row.update({field: data.get(field, 0) for field in SUMMARY_FIELDS})
            row.update({
                "appeals_sla": sla.get("appeals", 0),
                "answered": sla.get("answered", 0),
                "response_rate": sla.get("response_rate", 0.0),
                "median_hours": sla.get("median_hours"),
                "within_sla_rate": sla.get("within_sla_rate", 0.0),
            })
            summaries.append(row)
            print(f"  {period}: комментариев {row['total_comment_count']}, "
                  f"обращений {row['appeal_count']}, отвечено {row['answered']}")

            for item in data.get("category_breakdown", []):
                categories.append({"period": period, **item})

        publics = fetch(client, "/api/analytics/publics", token)
        pains = fetch(client, "/api/analytics/pains", token, period=periods[-1])

        # Не критичные для основной выгрузки ручки: на непересобранном проде
        # какой-то из них может не быть, и ронять из-за этого уже собранное
        # незачем — пишем предупреждение и идём дальше.
        def optional(path: str, **params):
            try:
                return fetch(client, path, token, **params)
            except httpx.HTTPError as exc:
                print(f"  пропущено {path}: {exc}")
                return []

        pain_map = optional("/api/analytics/pain-map", period=periods[-1])
        agencies = optional("/api/analytics/agency-ranking")
        alerts = optional("/api/analytics/alerts")
        incidents = optional("/api/analytics/incidents")
        daily = optional("/api/analytics/appeals/daily", since=since)

        me = optional("/api/auth/me")
        org_id = (me or {}).get("organization_id")
        health = optional(f"/api/organizations/{org_id}/data-health") if org_id else {}
        geo = optional("/api/analytics/address-cases/geocoding-stats")
        cases = fetch_address_cases(client, token, out)

    write_csv(out / "summary.csv", summaries, list(summaries[0].keys()))
    if categories:
        write_csv(out / "categories.csv", categories, list(categories[0].keys()))
    if publics:
        write_csv(out / "publics.csv", publics, list(publics[0].keys()))
        write_publics_links(out / "publics_links.csv", publics)
    if pains:
        write_csv(out / "pains.csv", pains, list(pains[0].keys()))
        write_pain_examples(out / "pain_examples.csv", pains)
    if pain_map:
        write_csv(out / "pain_map.csv", pain_map, list(pain_map[0].keys()))
    if agencies:
        write_csv(out / "agency_ranking.csv", agencies, list(agencies[0].keys()))
    if alerts:
        write_csv(out / "alerts.csv", alerts, list(alerts[0].keys()))
    if incidents:
        write_csv(out / "incidents.csv", incidents, list(incidents[0].keys()))
    if daily:
        write_csv(out / "appeals_by_day.csv", daily, list(daily[0].keys()))
        write_appeals_by_month(out / "appeals_by_month.csv", daily)
    if health:
        write_data_health(out / "classification_health.csv", health)
    if cases or geo:
        write_address_stats(out / "address_stats.csv", cases, geo or {})

    (out / "_raw_summary.json").write_text(
        json.dumps(summaries, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\nГотово: {out}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Выгрузка агрегатов СИГМЫ через API")
    parser.add_argument("--base-url", required=True, help="адрес бэкенда, например http://192.168.177.173:8000")
    parser.add_argument("--email", required=True)
    parser.add_argument("--password", help="без него спросят скрытым вводом")
    parser.add_argument("--periods", default=",".join(DEFAULT_PERIODS))
    parser.add_argument("--out", type=Path, default=Path("data/api_export"))
    parser.add_argument("--since", default="2025-06-01", help="начало помесячного ряда обращений")
    args = parser.parse_args(argv)

    password = args.password or getpass.getpass("Пароль: ")
    periods = [p.strip() for p in args.periods.split(",") if p.strip()]

    try:
        return export(args.base_url, args.email, password, periods, args.out, args.since)
    except httpx.HTTPStatusError as exc:
        print(f"Сервер ответил {exc.response.status_code}: {exc.response.text[:200]}")
        return 1
    except httpx.HTTPError as exc:
        print(f"Не удалось соединиться: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
