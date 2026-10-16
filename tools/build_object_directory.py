"""Собирает справочник объектов края из открытых данных Енисей-ГИС.

Геокодер не знает, где «школа №9» или «поликлиника на Судостроительной», и
отдаёт улицу или центр округа — по разметке это четверть оставшихся ошибок.
Открытые данные Енисей-ГИС отдают такие объекты с координатами, свободно и без
ключа, поэтому справочник кладётся в проект файлом и в рантайме никуда не
ходит: ни сети, ни квоты, ни зависимости от доступности портала.

Населённый пункт берётся из адреса объекта: без него искать нельзя, «школа №9»
есть в двух десятках городов края.

Запуск:
    python -m tools.build_object_directory
    python -m tools.build_object_directory --source D:/DS/enisey  # уже скачанное
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import urllib.request
from collections import Counter
from pathlib import Path

BASE = "https://24bpd.ru/files/opendata"

# Наборы, полезные для адресных кейсов. Ключ — тип объекта в справочнике.
DATASETS: dict[str, tuple[str, str]] = {
    "school": (
        "школы и учреждения образования",
        "2460210378-accreditededucationalinstitutions/data-20260228T0934-structure-20240630T1150.csv",
    ),
    "med": (
        "медицинские организации",
        "2466212607-rpomzkk/data-20260131T1250-structure-20240630T1150.csv",
    ),
    "stop": (
        "остановочные пункты",
        "2466231215-stoppingpoints/data-20250531T1612-structure-20240630T1152.csv",
    ),
    "emergency_home": (
        "аварийные дома",
        "2466231215-emergencyhomes/data-20260131T1252-structure-20240630T1152.csv",
    ),
    "culture": (
        "объекты культурного наследия",
        "2466231215-culturalheritageobjects/data-20260228T0934-structure-20240630T1150.csv",
    ),
    "road": (
        "дорожные объекты",
        "2466231215-roadobjects/data-20250531T1612-structure-20240630T1152.csv",
    ),
    "administration": (
        "органы местного самоуправления",
        "2466231215-administrationmunicipalities/data-20250531T1612-structure-20240630T1152.csv",
    ),
}

_PREFIX = r"(?:г|гор|город|с|село|п|пос|пгт|посёлок|поселок|д|деревня|ст|станция|рп|зато)"
# Второе слово только с заглавной: «Большая Мурта» — часть названия,
# «Вагино перекресток» — уже улица.
_RE_LOCALITY = re.compile(
    rf"\b{_PREFIX}\.?\s*([А-ЯЁ][а-яё]+(?:-[А-ЯЁа-яё]+|\s[А-ЯЁ][а-яё]+)?)", re.U
)
_NOT_LOCALITY = {"красноярский", "край", "российская", "россия"}
_RE_COUNCIL = re.compile(r"([А-ЯЁ][а-яё\-]+(?:ского|ский))\s+сельсовет", re.U)
_RE_DISTRICT = re.compile(
    r"([А-ЯЁ][а-яё\-]+(?:\s[А-ЯЁ][а-яё\-]+)?)\s*(?:муниципальн\w*\s*)?(?:район|р-н|округ)",
    re.U,
)


def locality_from_address(address: str) -> str:
    """Населённый пункт из адреса объекта."""
    text = " ".join((address or "").split())
    for match in _RE_LOCALITY.finditer(text):
        name = match.group(1).strip()
        if name.lower().split()[0] in _NOT_LOCALITY:
            continue
        return name
    return ""


def _download(relative: str, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(f"{BASE}/{relative}", timeout=120) as response:
        target.write_bytes(response.read())


def _rows(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def build(source: Path | None, out: Path) -> None:
    entries: list[dict] = []
    stats: Counter = Counter()

    for kind, (title, relative) in DATASETS.items():
        path = (source / f"{kind}.csv") if source else out.parent / "_raw" / f"{kind}.csv"
        if not path.exists():
            print(f"скачиваю {title}…")
            _download(relative, path)
        rows = _rows(path)

        kept = 0
        for row in rows:
            lat = (row.get("the_geom_lat") or "").strip()
            lon = (row.get("the_geom_lon") or "").strip()
            if not lat or not lon:
                continue
            address = (row.get("address") or "").strip()
            place = locality_from_address(address)
            if not place:
                continue
            # У аварийных домов имени нет — объект опознаётся по адресу.
            name = " ".join((row.get("name") or "").split()) or address
            try:
                entries.append({
                    "n": name[:200],
                    "a": " ".join(address.split())[:200],
                    "l": place,
                    "t": kind,
                    "lat": round(float(lat), 6),
                    "lon": round(float(lon), 6),
                })
            except ValueError:
                continue
            kept += 1

        stats[kind] = kept
        print(f"  {title:34} {kept:5} из {len(rows)}")

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(entries, ensure_ascii=False), encoding="utf-8")
    places = len({entry["l"] for entry in entries})
    print(f"\nвсего объектов: {len(entries)}, населённых пунктов: {places}")
    print(f"файл: {out} ({out.stat().st_size // 1024} КБ)")

    settlements = _settlement_municipalities(entries)
    target = out.with_name("settlement_municipality.json")
    target.write_text(json.dumps(settlements, ensure_ascii=False), encoding="utf-8")
    print(f"населённый пункт → округ: {len(settlements)}")
    print(f"файл: {target} ({target.stat().st_size // 1024} КБ)")


def _settlement_municipalities(entries: list[dict]) -> dict[str, str]:
    """Населённый пункт → муниципальный округ, из районов в адресах объектов.

    Автоподбор территории площадок узнаёт округа и крупные города, но не знает,
    что Диксон относится к Таймырскому округу, а Подтесово к Енисейскому. В
    адресах объектов район указан рядом с посёлком — этого достаточно.

    Посёлки-тёзки выбрасываются. Березовка есть в Абанском и Боготольском,
    Александровка — в восьми округах; по названию площадки различить их нельзя,
    а неверная территория хуже пустой. Раньше спор решался большинством — то
    есть тем, где в открытых данных случайно больше объектов.
    """
    from backend.modules.organization.municipalities import infer_krasnoyarsk_municipality

    votes: dict[str, Counter] = {}
    for entry in entries:
        # У части записей адрес без района — «п. Кузьмовка, ул. Кедровая, 2».
        # Тогда район берём из названия учреждения: «Кузьмовская начальная
        # школа Эвенкийского муниципального района».
        match = _RE_DISTRICT.search(entry.get("a", "")) or _RE_DISTRICT.search(entry.get("n", ""))
        if not match:
            continue
        municipality = infer_krasnoyarsk_municipality(match.group(0))
        if not municipality:
            continue
        votes.setdefault(entry["l"], Counter())[municipality] += 1

        # Сельсоветы называются прилагательным от села: «Администрация
        # Покатеевского сельсовета». Село в справочнике может отсутствовать, а
        # само прилагательное — готовый ключ для автоподбора территории.
        council = _RE_COUNCIL.search(entry.get("n", ""))
        if council:
            votes.setdefault(council.group(1), Counter())[municipality] += 1

    # «Каменск» и «Каменского» — одно название в разных записях, поэтому спор
    # ищем и по основе тоже: иначе тёзки расходятся по разным ключам и обе
    # версии выглядят однозначными.
    resolved = {
        place: counter.most_common(1)[0][0]
        for place, counter in sorted(votes.items())
        if len(counter) == 1
    }
    by_stem: dict[str, set[str]] = {}
    for place, municipality in resolved.items():
        by_stem.setdefault(_settlement_stem(place), set()).add(municipality)
    return {
        place: municipality
        for place, municipality in resolved.items()
        if len(by_stem[_settlement_stem(place)]) == 1
    }


_STEM_TAILS = (
    "ского", "ский", "ском", "ское", "ская",
    "ка", "ко", "ое", "ый", "ий", "а", "о", "е",
)


def _settlement_stem(name: str) -> str:
    """Основа названия: «Каменск», «Каменского» и «Каменка» дают одно и то же."""

    stem = name.lower().replace("ё", "е")
    for tail in _STEM_TAILS:
        if stem.endswith(tail) and len(stem) - len(tail) >= 4:
            stem = stem[: -len(tail)]
            break
    if stem.endswith("ск") and len(stem) > 5:
        stem = stem[:-2]
    return stem


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", help="папка с уже скачанными CSV")
    parser.add_argument("--out", default="data/object_directory.json")
    args = parser.parse_args()
    build(Path(args.source) if args.source else None, Path(args.out))


if __name__ == "__main__":
    main()
