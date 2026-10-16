"""Прогоняет размеченную выборку через текущую стратегию по кэшу ответов.

Замер точности обычно стоит обращений к геокодеру и суточной нормы ключей.
Но ответы провайдера на все запросы выборки уже сохранены (`tools/geo_cache`),
а меняем мы не их, а отбор: какие запросы строим и какие ответы принимаем.
Поэтому проверять правку можно офлайн, сколько угодно раз и бесплатно.

Считается то же, что и при ручной разметке:

* точность — доля верных среди принятых точек;
* покрытие — доля кейсов, для которых точка нашлась;
* «зря отбраковали» — доля отклонённых, которые разметчик считал верными.

Запуск:
    python -m tools.geo_replay
    python -m tools.geo_replay --label путь.xlsx --verdicts путь.csv
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path

from openpyxl import load_workbook

from backend.modules.analytics.utils.geocode import GeoPoint
from backend.modules.analytics.utils.location_geocode_strategy import (
    LocationContext,
    accept_geocode_result,
    build_geocode_queries,
)

DEFAULT_LABEL = r"D:\DS\mediahub-eval\gold\geo_label-yandex-2026-08-26-fixed.xlsx"
DEFAULT_VERDICTS = r"D:\DS\mediahub-eval\gold\verdicts-2026-08-26.csv"
DEFAULT_CACHE = r"D:\DS\mediahub-eval\results\geo_provider_cache.json"


def _point(entry: dict) -> GeoPoint | None:
    try:
        return GeoPoint(
            lat=float(entry["lat"]),
            lon=float(entry["lon"]),
            region=entry.get("region", ""),
            municipality=entry.get("municipality", ""),
            locality=entry.get("locality", ""),
            district=entry.get("district", ""),
            source=entry.get("source", ""),
            precision=entry.get("precision", ""),
            provider_name=entry.get("provider_name", ""),
            provider_description=entry.get("provider_description", ""),
            provider_kind=entry.get("provider_kind", ""),
            provider_text=entry.get("provider_text", ""),
        )
    except (KeyError, TypeError, ValueError):
        return None


def _rows(path: str) -> list[dict]:
    book = load_workbook(path, read_only=True, data_only=True)
    sheet = book["label"] if "label" in book.sheetnames else book.active
    stream = sheet.iter_rows(values_only=True)
    header = [str(name or "") for name in next(stream)]
    return [dict(zip(header, row)) for row in stream if any(row)]


def _verdicts(path: str) -> dict[str, str]:
    with open(path, encoding="utf-8-sig", newline="") as handle:
        return {
            str(row.get("id") or "").strip(): (row.get("вердикт") or "").strip().lower()
            for row in csv.DictReader(handle)
        }


def replay(label: str, verdicts_path: str, cache_path: str, provider: str = "yandex") -> Counter:
    cache = json.loads(Path(cache_path).read_text(encoding="utf-8"))
    verdicts = _verdicts(verdicts_path)
    counts: Counter = Counter()

    for row in _rows(label):
        case = str(row.get("адресный кейс") or "")
        if not case:
            continue
        counts["кейсов"] += 1
        context = LocationContext(
            case_name=case,
            public_region="Красноярский край",
            public_name=str(row.get("паблик") or ""),
            comment_text=str(row.get("комментарий") or ""),
        )
        region, queries = build_geocode_queries(context)

        accepted = None
        for query in queries:
            entry = cache.get(f"{provider}|{query}")
            if not entry:
                continue
            point = _point(entry)
            if point and accept_geocode_result(context, query, region, point):
                accepted = point
                break

        verdict = verdicts.get(str(row.get("id") or "").strip(), "")
        labelled = str(row.get("координата") or "").strip()

        if accepted is None:
            counts["без точки"] += 1
            # Разметчик считал прежнюю точку верной, а сейчас её нет.
            if verdict == "верно":
                counts["потеряли верную"] += 1
            continue

        counts["принято"] += 1
        # Вердикт относится к той точке, которую видел разметчик. Если приняли
        # другую, судить по старому вердикту нельзя — такие идут в «нужна
        # разметка», иначе цифры врут в свою пользу.
        same = labelled and _same_place(labelled, accepted)
        if same and verdict in {"верно", "неверно"}:
            counts[verdict] += 1
        else:
            counts["нужна разметка"] += 1

    return counts


def _same_place(labelled: str, point: GeoPoint) -> bool:
    """Та же точка, что видел разметчик (с точностью до сотых долей градуса)."""
    try:
        lat, lon = (float(part) for part in labelled.split(",")[:2])
    except (TypeError, ValueError):
        return False
    return abs(lat - point.lat) < 0.001 and abs(lon - point.lon) < 0.001


def report(counts: Counter) -> None:
    judged = counts["верно"] + counts["неверно"]
    precision = counts["верно"] * 100 / judged if judged else 0
    recall = counts["принято"] * 100 / counts["кейсов"] if counts["кейсов"] else 0
    print(f"кейсов            {counts['кейсов']}")
    print(f"принято точек     {counts['принято']}  (покрытие {recall:.1f}%)")
    print(f"  верных          {counts['верно']}")
    print(f"  неверных        {counts['неверно']}")
    print(f"точность          {precision:.1f}%  (по {judged} сопоставимым точкам)")
    print(f"нужна разметка    {counts['нужна разметка']}  — приняли точку, которой разметчик не видел")
    print(f"потеряли верных   {counts['потеряли верную']}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", default=DEFAULT_LABEL)
    parser.add_argument("--verdicts", default=DEFAULT_VERDICTS)
    parser.add_argument("--cache", default=DEFAULT_CACHE)
    parser.add_argument("--provider", default="yandex")
    args = parser.parse_args()
    report(replay(args.label, args.verdicts, args.cache, args.provider))


if __name__ == "__main__":
    main()
