"""Сравнение провайдеров на одной выборке и отбор расхождений для разметки.

Берёт файлы `tools/geo_label`, снятые разными провайдерами на одном наборе
кейсов, и выравнивает их по id. Показывает, кто сколько нашёл и насколько
ответы совпадают между собой.

Смысл в экономии ручного труда: там, где провайдеры указали на одно и то же
место, вердикт из разметки базового провайдера годится для всех. Размечать
нужно только расхождения — их и выгружает `--out`.

Запуск:
    python -m tools.geo_compare yandex.xlsx 2gis.xlsx dadata.xlsx --out diff.xlsx
"""
from __future__ import annotations

import argparse
import csv
from collections import Counter
from pathlib import Path

from openpyxl import Workbook

from tools.geo_eval import distance_km
from tools.geo_label import STATUS_FOUND, STATUS_REJECTED, _read

SAME_PLACE_KM = 1.0


def _point(row: dict) -> tuple[float, float] | None:
    """Точка, которую система реально поставила бы на карту.

    У отклонённых кандидатов координата в файле тоже есть — она нужна
    разметчику, но в сравнение провайдеров идти не должна.
    """
    if str(row.get("статус") or "") != STATUS_FOUND:
        return None
    raw = str(row.get("координата") or "")
    if not raw:
        return None
    lat, _, lon = raw.partition(",")
    try:
        return float(lat), float(lon)
    except ValueError:
        return None


def _load(path: str) -> dict[str, dict]:
    return {str(row.get("id") or ""): row for row in _read(path)}


def compare(paths: list[str], out: str | None) -> None:
    names = [Path(path).stem.replace("geo_label_", "") for path in paths]
    tables = [_load(path) for path in paths]
    base_name, base = names[0], tables[0]

    print(f"{'провайдер':26} {'нашли':>6} {'не приняли':>11} {'только регион':>14}")
    for name, table in zip(names, tables):
        statuses = Counter(str(row.get("статус") or "") for row in table.values())
        print(f"{name:26} {statuses[STATUS_FOUND]:6} {statuses['не приняли ответ']:11} "
              f"{statuses['только регион']:14}")

    print()
    print(f"согласие с базовым «{base_name}» (одно место = ближе {SAME_PLACE_KM} км)")
    print(f"{'провайдер':26} {'оба нашли':>10} {'то же место':>12} {'разошлись':>10} "
          f"{'только он':>10} {'только базовый':>15}")

    disagreements: dict[str, dict] = {}
    for name, table in list(zip(names, tables))[1:]:
        counts: Counter = Counter()
        for case_id, base_row in base.items():
            other_row = table.get(case_id)
            if other_row is None:
                continue
            base_point, other_point = _point(base_row), _point(other_row)
            if base_point and other_point:
                counts["оба нашли"] += 1
                if distance_km(base_point, other_point) <= SAME_PLACE_KM:
                    counts["то же место"] += 1
                else:
                    counts["разошлись"] += 1
                    disagreements.setdefault(case_id, base_row)
            elif other_point:
                counts["только он"] += 1
                disagreements.setdefault(case_id, base_row)
            elif base_point:
                counts["только базовый"] += 1
        print(f"{name:26} {counts['оба нашли']:10} {counts['то же место']:12} "
              f"{counts['разошлись']:10} {counts['только он']:10} {counts['только базовый']:15}")

    print()
    print(f"кейсов, где хоть один провайдер расходится с базовым: {len(disagreements)}")

    if out:
        _write_diff(out, names, tables, disagreements)
        print(f"файл расхождений: {out}")


def _write_diff(out: str, names: list[str], tables: list[dict], disagreements: dict[str, dict]) -> None:
    book = Workbook()
    sheet = book.active
    sheet.title = "diff"
    header = ["id", "слой", "паблик", "адресный кейс"]
    for name in names:
        header += [f"{name}: что нашёл", f"{name}: координата"]
    sheet.append(header)

    for case_id in sorted(disagreements):
        base_row = disagreements[case_id]
        line = [case_id, base_row.get("слой"), base_row.get("паблик"), base_row.get("адресный кейс")]
        for table in tables:
            row = table.get(case_id) or {}
            line += [row.get("что нашёл геокодер") or "", row.get("координата") or ""]
        sheet.append(line)

    sheet.freeze_panes = "A2"
    book.save(out)


def _load_verdicts(path: str) -> list[tuple[str, tuple[float, float], str]]:
    """Вердикты со страницы разметки: кейс, координата места, оценка."""
    result = []
    with open(path, encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            verdict = str(row.get("вердикт") or "").strip().lower()
            raw = str(row.get("координата") or "")
            lat, _, lon = raw.partition(",")
            try:
                point = (float(lat), float(lon))
            except ValueError:
                continue
            if verdict:
                result.append((str(row.get("id") or ""), point, verdict))
    return result


def score(paths: list[str], verdicts_path: str) -> None:
    """Точность каждого провайдера и цена нашей отбраковки — по одной разметке."""
    verdicts = _load_verdicts(verdicts_path)
    by_case: dict[str, list] = {}
    for case_id, point, verdict in verdicts:
        by_case.setdefault(case_id, []).append((point, verdict))

    def verdict_for(case_id: str, point: tuple[float, float]) -> str:
        for other, verdict in by_case.get(case_id, ()):
            if distance_km(other, point) <= SAME_PLACE_KM:
                return verdict
        return ""

    print(f"{'провайдер':24} {'принято':>8} {'верно':>6} {'неверно':>8} {'не адрес':>9} "
          f"{'ТОЧНОСТЬ':>9} {'зря отброшено':>14}")
    for path in paths:
        table = _load(path)
        counts: Counter = Counter()
        for case_id, row in table.items():
            point = _point(row)
            status = str(row.get("статус") or "")
            if point is not None:
                verdict = verdict_for(case_id, point)
                counts["принято"] += 1
                if verdict:
                    counts[verdict] += 1
            elif status == STATUS_REJECTED:
                raw = str(row.get("координата") or "")
                lat, _, lon = raw.partition(",")
                try:
                    dropped = (float(lat), float(lon))
                except ValueError:
                    continue
                if verdict_for(case_id, dropped) == "верно":
                    counts["зря отброшено"] += 1
        judged = counts["верно"] + counts["неверно"]
        precision = f"{counts['верно'] * 100 / judged:.0f}%" if judged else "—"
        print(f"{_provider(path):24} {counts['принято']:8} {counts['верно']:6} {counts['неверно']:8} "
              f"{counts['не адрес']:9} {precision:>9} {counts['зря отброшено']:14}")

    unjudged = sum(1 for _case, _point, verdict in verdicts if not verdict)
    if unjudged:
        print()
        print(f"без вердикта: {unjudged}")


def _provider(path: str) -> str:
    return Path(path).stem.replace("geo_label-", "").replace("geo_label_", "")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", help="файлы geo_label; первый — базовый")
    parser.add_argument("--out", help="куда выгрузить расхождения")
    parser.add_argument("--verdicts", help="CSV со страницы разметки — тогда считается точность")
    args = parser.parse_args()
    if args.verdicts:
        score(args.paths, args.verdicts)
        return
    compare(args.paths, args.out)


if __name__ == "__main__":
    main()
