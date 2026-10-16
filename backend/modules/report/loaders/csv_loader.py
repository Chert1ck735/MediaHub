"""Загрузка спаршенных постов VK и Дзена из CSV-файлов.

Legacy-вход. В типовом сценарии посты приходят из БД (см.
``repositories/post_repository.py``); CSV остался для случаев, когда
ввод приходит файлом — например, ручной перевыгрузки от подрядчика.

Обе функции читают CSV с разделителем ``;`` и BOM-aware кодировкой
``utf-8-sig`` (Excel любит сохранять с BOM). Возвращают список словарей
с сырыми строковыми значениями — нормализация / приведение типов
происходит дальше в analyzers.
"""
from __future__ import annotations

import csv
from pathlib import Path


def load_vk_data(path: str | Path) -> list[dict]:
    """Читает CSV-выгрузку VK; возвращает пустой список, если файла нет."""

    p = Path(path)
    if not p.exists():
        return []
    with p.open(encoding="utf-8-sig", newline="") as f:
        return [row for row in csv.DictReader(f, delimiter=";")]


def load_dzen_data(path: str | Path) -> list[dict]:
    """Читает CSV-выгрузку Дзена; возвращает пустой список, если файла нет."""

    p = Path(path)
    if not p.exists():
        return []
    with p.open(encoding="utf-8-sig", newline="") as f:
        return [row for row in csv.DictReader(f, delimiter=";")]
