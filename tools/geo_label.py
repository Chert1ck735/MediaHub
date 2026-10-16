"""Геокодит выборку и готовит данные для ручной разметки.

Прогоняет кейсы из `tools/geo_sample` через выбранного провайдера по боевой
стратегии (варианты запросов плюс отбраковка чужих точек) и складывает
результат в XLSX. Размечать удобнее в браузере — страницу собирает
`tools/geo_review`.

Мерим две вещи. Первая и главная — точность: неверная точка на карте хуже
отсутствующей. Вторая — не слишком ли строга отбраковка: если геокодер дал
верный объект, а стратегия его не приняла, это тоже ошибка, просто обратная.
Поэтому размечаются и принятые точки, и отклонённые кандидаты.

Статусы строки:
  * `нашли`             — точка принята, нужен вердикт о её верности;
  * `не приняли ответ`  — геокодер дал конкретный объект, стратегия отказалась;
  * `только регион`     — геокодер не нашёл ничего конкретнее региона, судить нечего.

Ответы провайдера кэшируются (`tools/geo_cache`), поэтому повторный прогон
той же выборки квоту не тратит.

Запуск:
    python -m tools.geo_label geo_sample.xlsx --provider yandex --out geo_label.xlsx
    python -m tools.geo_label geo_label.xlsx --score --verdicts verdicts.csv
"""
from __future__ import annotations

import argparse
import csv
import time
from collections import Counter, defaultdict

from openpyxl import Workbook, load_workbook
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

from backend.modules.analytics.utils.location_geocode_strategy import (
    LocationContext,
    accept_geocode_result,
    build_geocode_queries,
)
from tools.geo_cache import DEFAULT_PATH, GeoCache
from tools.geo_providers import MIN_PAUSE_SECONDS, PROVIDERS

STATUS_FOUND = "нашли"
STATUS_REJECTED = "не приняли ответ"
STATUS_ONLY_REGION = "только регион"
STATUS_ERROR = "ошибка провайдера"

# Вердикты для принятых точек и для отклонённых кандидатов — разные вопросы.
VERDICTS_FOUND = ("верно", "неверно", "не адрес")
VERDICTS_REJECTED = ("надо было принять", "правильно отбраковали")
VERDICTS = VERDICTS_FOUND + VERDICTS_REJECTED

DATA_SHEET = "label"

OUT_COLUMNS = (
    "id", "слой", "паблик", "город паблика", "адресный кейс",
    "статус", "запрос", "что нашёл геокодер", "координата",
    "карта", "вердикт", "заметка", "комментарий",
)


def _read(path: str) -> list[dict]:
    book = load_workbook(path, read_only=True, data_only=True)
    sheet = book[DATA_SHEET] if DATA_SHEET in book.sheetnames else book.active
    stream = sheet.iter_rows(values_only=True)
    header = [str(name or "") for name in next(stream)]
    return [dict(zip(header, row)) for row in stream if any(row)]


def _context(row: dict) -> LocationContext:
    return LocationContext(
        case_name=str(row.get("адресный кейс") or ""),
        public_region=str(row.get("регион паблика") or ""),
        public_name=str(row.get("паблик") or ""),
        comment_text=str(row.get("комментарий") or ""),
        address=str(row.get("entities.address") or ""),
    )


def _ask(fn, query: str, timeout: int):
    """Сетевая ошибка не должна ронять прогон: одна повторная попытка, потом пропуск."""
    for attempt in (1, 2):
        try:
            return fn(query, timeout), True
        except Exception as error:  # noqa: BLE001 — провайдер отваливается по таймауту или квоте
            if attempt == 2:
                print(f"  провайдер не ответил на {query!r}: {error}")
                return None, False
            time.sleep(2.0)
    return None, False


def _is_concrete(point) -> bool:
    """Ответ конкретнее региона: по нему есть о чём спрашивать разметчика."""
    return bool(point.locality or point.municipality)


def _geocode(fn, context: LocationContext, timeout: int, pause: float):
    """Повторяет боевой обход: первый принятый вариант выигрывает.

    Если не принят ни один, возвращает лучшего отклонённого кандидата — его
    разметка и покажет, не слишком ли строга отбраковка.
    """
    region, queries = build_geocode_queries(context)
    rejected: tuple[str, object] | None = None
    failed = False
    for query in queries:
        point, answered = _ask(fn, query, timeout)
        failed = failed or not answered
        if pause:
            time.sleep(pause)
        if point is None:
            continue
        if accept_geocode_result(context, query, region, point):
            return query, point, STATUS_FOUND
        if rejected is None and _is_concrete(point):
            rejected = (query, point)
    if rejected is not None:
        return rejected[0], rejected[1], STATUS_REJECTED
    return "", None, STATUS_ERROR if failed else STATUS_ONLY_REGION


def build(path: str, *, provider: str, out: str, limit: int, timeout: int, cache_path: str) -> None:
    rows = _read(path)
    if limit:
        rows = rows[:limit]
    cache = GeoCache(cache_path)
    fn = cache.wrap(provider, PROVIDERS[provider])
    pause = MIN_PAUSE_SECONDS.get(provider, 0.0)

    book = Workbook()
    sheet = book.active
    sheet.title = DATA_SHEET
    sheet.append(list(OUT_COLUMNS))

    statuses: Counter = Counter()
    for row in rows:
        query, point, status = _geocode(fn, _context(row), timeout, pause)
        statuses[status] += 1
        sheet.append([
            row.get("id"),
            row.get("слой"),
            row.get("паблик"),
            row.get("город паблика"),
            row.get("адресный кейс"),
            status,
            query,
            point.provider_text if point else "",
            f"{point.lat}, {point.lon}" if point else "",
            f"https://yandex.ru/maps/?pt={point.lon},{point.lat}&z=16&l=map" if point else "",
            "",
            "",
            str(row.get("комментарий") or "")[:400],
        ])

    _decorate(sheet, len(rows))
    book.save(out)
    cache.save()

    total = sum(statuses.values())
    print(f"провайдер: {provider}, кейсов: {total}")
    for status in (STATUS_FOUND, STATUS_REJECTED, STATUS_ONLY_REGION, STATUS_ERROR):
        count = statuses[status]
        print(f"  {status:20} {count:4} ({count * 100 // total if total else 0}%)")
    print(cache.report())
    to_label = statuses[STATUS_FOUND] + statuses[STATUS_REJECTED]
    print(f"размечать нужно {to_label} строк")
    print(f"файл: {out}")


def _decorate(sheet, row_count: int) -> None:
    """Выпадающий список вердиктов и ширины колонок — на случай разметки прямо в Excel."""
    column = get_column_letter(OUT_COLUMNS.index("вердикт") + 1)
    validation = DataValidation(
        type="list",
        formula1='"' + ",".join(VERDICTS) + '"',
        allow_blank=True,
        showDropDown=False,
    )
    sheet.add_data_validation(validation)
    validation.add(f"{column}2:{column}{row_count + 1}")

    widths = {
        "id": 12, "слой": 9, "паблик": 32, "город паблика": 16,
        "адресный кейс": 38, "статус": 18, "запрос": 42,
        "что нашёл геокодер": 46, "координата": 20, "карта": 46,
        "вердикт": 20, "заметка": 24, "комментарий": 60,
    }
    for name, width in widths.items():
        sheet.column_dimensions[get_column_letter(OUT_COLUMNS.index(name) + 1)].width = width
    sheet.freeze_panes = "A2"


def _load_verdicts(path: str) -> dict[str, tuple[str, str]]:
    """Читает выгрузку страницы разметки: id, вердикт, заметка."""
    with open(path, encoding="utf-8-sig", newline="") as handle:
        return {
            str(row.get("id") or ""): (
                str(row.get("вердикт") or "").strip().lower(),
                str(row.get("заметка") or ""),
            )
            for row in csv.DictReader(handle)
        }


def score(path: str, verdicts_path: str | None) -> None:
    rows = _read(path)
    verdicts = _load_verdicts(verdicts_path) if verdicts_path else {}

    by_layer: dict[str, Counter] = defaultdict(Counter)
    for row in rows:
        layer = str(row.get("слой") or "—")
        status = str(row.get("статус") or "")
        verdict = verdicts.get(str(row.get("id") or ""), ("", ""))[0]
        if not verdict:
            verdict = str(row.get("вердикт") or "").strip().lower()

        counts = by_layer[layer]
        counts["всего"] += 1
        if status == STATUS_FOUND:
            counts["нашли"] += 1
            counts[verdict if verdict in VERDICTS_FOUND else "не размечено"] += 1
        elif status == STATUS_REJECTED:
            counts["отбраковано"] += 1
            counts[verdict if verdict in VERDICTS_REJECTED else "не размечено"] += 1

    print(f"{'слой':10} {'всего':>6} {'нашли':>6} {'верно':>6} {'неверно':>8} {'не адрес':>9} "
          f"{'точность':>9} {'полнота':>8} {'зря отбраковали':>16}")
    total: Counter = Counter()
    for layer in sorted(by_layer):
        total.update(by_layer[layer])
        print(_line(layer, by_layer[layer]))
    print(_line("итого", total))

    if total["не размечено"]:
        print(f"\nещё не размечено: {total['не размечено']} строк")


def _line(name: str, counts: Counter) -> str:
    judged = counts["верно"] + counts["неверно"]
    precision = f"{counts['верно'] * 100 / judged:.0f}%" if judged else "—"
    recall = f"{counts['нашли'] * 100 / counts['всего']:.0f}%" if counts["всего"] else "—"
    over = counts["надо было принять"] + counts["правильно отбраковали"]
    over_rate = f"{counts['надо было принять'] * 100 / over:.0f}%" if over else "—"
    return (
        f"{name:10} {counts['всего']:6} {counts['нашли']:6} {counts['верно']:6} "
        f"{counts['неверно']:8} {counts['не адрес']:9} {precision:>9} {recall:>8} {over_rate:>16}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", help="XLSX выборки или файл разметки при --score")
    parser.add_argument("--score", action="store_true", help="посчитать метрики по вердиктам")
    parser.add_argument("--verdicts", help="CSV со страницы разметки (tools/geo_review)")
    parser.add_argument("--provider", choices=sorted(PROVIDERS), default="yandex")
    parser.add_argument("--out", default="geo_label.xlsx")
    parser.add_argument("--limit", type=int, default=0, help="взять только первые N строк")
    parser.add_argument("--timeout", type=int, default=15)
    parser.add_argument("--cache", default=str(DEFAULT_PATH))
    args = parser.parse_args()

    if args.score:
        score(args.path, args.verdicts)
        return
    build(args.path, provider=args.provider, out=args.out, limit=args.limit,
          timeout=args.timeout, cache_path=args.cache)


if __name__ == "__main__":
    main()
