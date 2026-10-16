"""Сравнение геокодеров на реальных адресных кейсах из базы.

Гоняет одни и те же запросы через доступных провайдеров и печатает, кто
сколько нашёл и сколько точек попало в ожидаемый регион. Кэш не трогает,
в базу не пишет. Нужен, чтобы выбирать провайдера по данным, а не по обещаниям
на сайте.

Провайдер участвует, если настроен: Яндекс — при YANDEX_GEOCODER_KEY,
DaData — при DADATA_TOKEN/SECRET, OSM — всегда (не чаще 1 запроса в секунду).

Запуск:  python -m tools.geo_bench [--limit 60] [--region "Красноярский край"]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import time
from collections import Counter

from sqlalchemy import select

from backend.db.comment_analysis import CommentAnalysis
from backend.db.comments import Comment
from backend.db.database import async_session_maker
from backend.modules.analytics.utils.case_extractor import (
    case_location_key,
    is_valid_case_title,
)
from backend.modules.analytics.utils.location_geocode_strategy import (
    LocationContext,
    build_geocode_queries,
)
from tools.geo_providers import PROVIDERS


async def load_queries(limit: int, region: str) -> list[tuple[str, str]]:
    async with async_session_maker() as session:
        rows = (
            await session.execute(
                select(CommentAnalysis.hierarchy, Comment.text)
                .join(Comment, Comment.id == CommentAnalysis.comment_id)
                .where(CommentAnalysis.hierarchy.isnot(None))
            )
        ).all()

    seen: set[str] = set()
    cases: list[tuple[str, str]] = []
    for hierarchy, text in rows:
        data = hierarchy if isinstance(hierarchy, dict) else json.loads(hierarchy or "{}")
        title = str((data or {}).get("case") or "").strip()
        if not title or not is_valid_case_title(title):
            continue
        key = case_location_key(title) or title.lower()
        if key in seen:
            continue
        seen.add(key)
        _, queries = build_geocode_queries(
            LocationContext(case_name=title, public_region=region, comment_text=str(text or ""))
        )
        if queries:
            cases.append((title, queries[0]))
        if len(cases) >= limit:
            break
    return cases


def run(cases: list[tuple[str, str]], region: str, timeout: int) -> None:
    stats: dict[str, Counter] = {name: Counter() for name in PROVIDERS}
    region_key = region.lower()[:12]

    for index, (_title, query) in enumerate(cases, 1):
        for name, fn in PROVIDERS.items():
            try:
                point = fn(query, timeout)
            except Exception:  # noqa: BLE001 — недоступность провайдера не роняет прогон
                point = None
            stats[name]["total"] += 1
            if point is None:
                continue
            stats[name]["found"] += 1
            if region_key in str(getattr(point, "region", "")).lower():
                stats[name]["in_region"] += 1
        time.sleep(1.1)  # ограничение Nominatim
        if index % 20 == 0:
            print(f"  обработано {index}/{len(cases)}")

    print()
    for name, counter in stats.items():
        total, found = counter["total"], counter["found"]
        if not total or not found:
            print(f"{name:15} не настроен или ничего не нашёл")
            continue
        print(
            f"{name:15} нашёл {found}/{total} ({found * 100 // total}%), "
            f"в регионе {counter['in_region']} ({counter['in_region'] * 100 // found}%)"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=60, help="сколько адресов взять")
    parser.add_argument("--region", default="Красноярский край", help="ожидаемый регион")
    parser.add_argument("--timeout", type=int, default=15)
    args = parser.parse_args()

    cases = asyncio.run(load_queries(args.limit, args.region))
    print(f"адресов в выборке: {len(cases)}\n")
    run(cases, args.region, args.timeout)


if __name__ == "__main__":
    main()
