"""Справочник объектов края: школа, больница, остановка — сразу в координаты.

Геокодер не знает, где «школа №9» или «поликлиника на Судостроительной»: он
отдаёт улицу, центр округа или вовсе чужой город. По разметке 530 мест это
четверть оставшихся ошибок.

Справочник собран из открытых данных Енисей-ГИС (`tools/build_object_directory`)
и лежит файлом в проекте, поэтому поиск ничего не стоит: ни сети, ни квоты.

Точность важнее полноты, как и во всей стратегии. Поэтому:

* без населённого пункта не ищем вовсе — «школа №9» есть в двух десятках
  городов края;
* номер объекта сравнивается как отдельное число, чтобы «школа 9» не совпала
  с «школой 19»;
* два кандидата в одном населённом пункте — отказ. Пусть лучше точки не будет.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

from backend.app.config import PROJECT_ROOT

DIRECTORY_PATH = PROJECT_ROOT / "data" / "object_directory.json"

# Слова, по которым кейс опознаётся как объект, и тип в справочнике.
_KIND_MARKERS: tuple[tuple[str, str], ...] = (
    ("школ", "school"),
    ("сош", "school"),
    ("оош", "school"),
    ("гимнази", "school"),
    ("лице", "school"),
    ("детск сад", "school"),
    ("детсад", "school"),
    ("больниц", "med"),
    ("поликлиник", "med"),
    ("амбулатор", "med"),
    ("диспансер", "med"),
    ("фап", "med"),
    ("остановк", "stop"),
    ("остановочн", "stop"),
    # Администрации намеренно не ищем: кейс «Администрация города Дивногорска»
    # почти всегда обрывок обращения к площадке, а не жалоба на здание. Ставить
    # по нему точку на мэрию — рисовать на карте несуществующую проблему.
    ("музе", "culture"),
    ("памятник", "culture"),
    ("церк", "culture"),
    ("храм", "culture"),
    ("собор", "culture"),
)

# Типы, где единственный объект в населённом пункте — это и есть тот самый:
# больница в городе обычно одна. Школ, остановок и памятников много, и
# единственная запись в справочнике не значит, что речь именно о ней.
_UNIQUE_BY_NATURE = frozenset({"med"})

_RE_NUMBER = re.compile(r"\d+")
_RE_WORD = re.compile(r"[а-яёa-z]+", re.U)


@dataclass(frozen=True)
class ObjectHit:
    name: str
    address: str
    locality: str
    kind: str
    lat: float
    lon: float


_entries: list[dict] | None = None
_index: dict[tuple[str, str], list[dict]] = {}


def _norm(value: str) -> str:
    return " ".join((value or "").lower().replace("ё", "е").split())


def _load() -> None:
    """Читает справочник один раз на процесс. Нет файла — поиск просто молчит."""
    global _entries
    if _entries is not None:
        return
    try:
        _entries = json.loads(DIRECTORY_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        _entries = []
        return
    for entry in _entries:
        key = (_norm(entry.get("l", "")), entry.get("t", ""))
        _index.setdefault(key, []).append(entry)


def available() -> bool:
    _load()
    return bool(_entries)


def _kind_of(case_name: str) -> str:
    low = _norm(case_name)
    for marker, kind in _KIND_MARKERS:
        if marker in low:
            return kind
    return ""


def _numbers(value: str) -> set[str]:
    return set(_RE_NUMBER.findall(value or ""))


def _words(value: str) -> set[str]:
    return {word for word in _RE_WORD.findall(_norm(value)) if len(word) >= 5}


def find_object(case_name: str, locality: str) -> ObjectHit | None:
    """Единственный объект такого типа с таким номером в этом населённом пункте."""

    _load()
    if not _entries or not case_name or not locality:
        return None

    kind = _kind_of(case_name)
    if not kind:
        return None

    candidates = _index.get((_norm(locality), kind))
    if not candidates:
        return None

    case_numbers = _numbers(case_name)
    if case_numbers:
        matched = [
            entry for entry in candidates
            if case_numbers & _numbers(entry.get("n", ""))
        ]
    elif len(candidates) == 1 and kind in _UNIQUE_BY_NATURE:
        # Единственный объект такого типа в населённом пункте: «около больницы»
        # в Емельянове двусмысленным быть не может. Для школ так нельзя — в
        # округе их много, а в справочнике может быть только райцентровская, и
        # «Лебедевская школа Каратузского округа» уехала бы в Каратузское.
        matched = candidates
    else:
        # Иначе опираемся на редкие слова названия: «краевая клиническая
        # больница». Короткие служебные слова отброшены в `_words`.
        case_words = _words(case_name) - {"школа", "больница", "остановка"}
        # Название самого населённого пункта совпадением не считается: иначе
        # «Емельяновский район, Совхоз Сибиряк, школа» цепляется за любой
        # емельяновский объект, хотя речь про школу в совхозе.
        stem = _norm(locality)[:5]
        case_words = {word for word in case_words if not word.startswith(stem)}
        if not case_words:
            return None
        matched = [
            entry for entry in candidates
            if case_words & _words(entry.get("n", ""))
        ]

    if len(matched) != 1:
        return None

    entry = matched[0]
    return ObjectHit(
        name=entry.get("n", ""),
        address=entry.get("a", ""),
        locality=entry.get("l", ""),
        kind=entry.get("t", ""),
        lat=float(entry["lat"]),
        lon=float(entry["lon"]),
    )
