"""Отчёт о качестве разметки: подкатегории и адреса. Без LLM.

Метрики снимаются до и после изменений, чтобы видеть «было/стало»:

Подкатегории
  * покрытие — доля обращений с непустой подкатегорией (по категориям);
  * соответствие таксономии — доля пар «категория → подкатегория», где
    подкатегория принадлежит своей категории;
  * распределение по подкатегориям внутри категории.

Адреса
  * покрытие геокодингом — доля адресных кейсов с координатами;
  * «свой муниципалитет» — доля точек, попавших в город паблика. Для паблика
    с известным городом точка в другом муниципалитете почти всегда ошибка,
    если этот город не назван в тексте комментария.

Запуск на сервере (есть база и geo-cache):
    python -m tools.quality_report [--json before.json] [--since 2026-01-01]

Запуск с рабочей машины (база недоступна) — через API, как sigma_export_api:
    python -m tools.quality_report --base-url https://sigma.krskcit.ru --email me@krskcit.ru
"""
from __future__ import annotations

import argparse
import asyncio
import getpass
import json
from datetime import datetime

import httpx


def render(report: dict) -> str:
    subs, addr = report["subcategories"], report["addresses"]
    lines = [
        "ПОДКАТЕГОРИИ",
        f"  обращений с категорией: {subs['appeals']}",
        f"  с подкатегорией: {subs['with_subcategory_pct']}%",
        f"  вне таксономии: {subs['off_taxonomy']} ({subs['off_taxonomy_pct']}% от заполненных)",
        "",
    ]
    for category, data in subs["categories"].items():
        top = ", ".join(f"{name} {count}" for name, count in data["top"])
        lines.append(
            f"  {category}: {data['appeals']} обращений, "
            f"с подкатегорией {data['with_subcategory_pct']}%"
        )
        lines.append(f"    топ: {top}")

    if addr.get("error"):
        lines += ["", "АДРЕСА", f"  {addr['error']}"]
        return "\n".join(lines)

    lines += [
        "",
        "АДРЕСА",
        f"  адресных кейсов: {addr['cases']}",
        f"  геокодировано: {addr['geocoded']} ({addr['geocoded_pct']}%)",
        f"  проверяемых (город паблика известен): {addr['checkable']}",
        f"  точка в городе паблика: {addr['in_public_city']} ({addr['in_public_city_pct']}%)",
    ]
    if addr.get("by_source"):
        lines.append("  по геокодерам:")
        for name, data in addr["by_source"].items():
            lines.append(
                f"    {name:16} точек {data['geocoded']}, из проверяемых "
                f"{data['in_public_city']}/{data['checkable']} в городе паблика "
                f"({data['in_public_city_pct']}%), мимо {data.get('mismatched', 0)}"
            )
    if addr["top_mismatches"]:
        lines.append("  частые расхождения:")
        lines += [f"    {name}: {count}" for name, count in addr["top_mismatches"]]
    return "\n".join(lines)


async def report_from_db(since: datetime | None) -> dict:
    from backend.db.database import async_session_maker
    from backend.modules.analytics.services.quality_report_service import (
        build_quality_report,
    )

    async with async_session_maker() as session:
        return await build_quality_report(session, since)


def report_from_api(base_url: str, email: str, since: str | None) -> dict:
    password = getpass.getpass(f"Пароль для {email}: ")
    with httpx.Client(base_url=base_url.rstrip("/"), timeout=300) as client:
        response = client.post("/api/auth/login", json={"email": email, "password": password})
        response.raise_for_status()
        token = response.json()["access_token"]

        params = {"since": since} if since else {}
        response = client.get(
            "/api/analytics/quality-report",
            params=params,
            headers={"Authorization": f"Bearer {token}"},
        )
        response.raise_for_status()
        return response.json()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--since", help="учитывать разметку с этой даты, ГГГГ-ММ-ДД")
    parser.add_argument("--json", dest="json_path", help="сохранить отчёт в JSON")
    parser.add_argument("--base-url", help="считать через API, а не из базы")
    parser.add_argument("--email", help="аккаунт для входа, нужен с --base-url")
    args = parser.parse_args()

    if args.base_url:
        if not args.email:
            parser.error("с --base-url нужен --email")
        report = report_from_api(args.base_url, args.email, args.since)
    else:
        since = datetime.fromisoformat(args.since) if args.since else None
        report = asyncio.run(report_from_db(since))

    print(render(report))
    if args.json_path:
        with open(args.json_path, "w", encoding="utf-8") as handle:
            json.dump(report, handle, ensure_ascii=False, indent=2)
        print(f"\nJSON: {args.json_path}")


if __name__ == "__main__":
    main()
