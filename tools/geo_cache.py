"""Файловый кэш ответов геокодеров для оффлайновых прогонов.

Провайдеры лимитированы (бесплатный ключ Яндекса — 1000 запросов в сутки,
демо-ключ 2ГИС — 1000 в месяц), а стратегия запросов меняется часто. Кэш
хранит разобранный ответ по паре «провайдер + запрос», поэтому повторный
прогон той же выборки квоту не тратит, а новых обращений требуют только
новые формулировки запроса.

Кэш инструментов замера намеренно отдельный от боевого geo-cache карты болей:
здесь допустимо держать и отрицательные ответы, и результаты провайдеров,
которые в продакшене не включены.
"""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Callable

from backend.modules.analytics.utils.geocode import GeoPoint

Provider = Callable[[str, int], GeoPoint | None]

DEFAULT_PATH = Path("data/eval/geo_provider_cache.json")


class GeoCache:
    def __init__(self, path: str | Path = DEFAULT_PATH) -> None:
        self.path = Path(path)
        self.hits = 0
        self.misses = 0
        self._dirty = False
        self._entries: dict[str, dict | None] = {}
        if self.path.exists():
            self._entries = json.loads(self.path.read_text(encoding="utf-8"))

    def wrap(self, provider: str, fn: Provider) -> Provider:
        """Оборачивает функцию провайдера так, чтобы повтор шёл из кэша."""

        def call(address: str, timeout: int) -> GeoPoint | None:
            key = f"{provider}|{address}"
            if key in self._entries:
                self.hits += 1
                payload = self._entries[key]
                return GeoPoint(**payload) if payload else None
            self.misses += 1
            point = fn(address, timeout)
            self._entries[key] = asdict(point) if point else None
            self._dirty = True
            return point

        return call

    def save(self) -> None:
        if not self._dirty:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(self._entries, ensure_ascii=False, indent=1),
            encoding="utf-8",
        )
        self._dirty = False

    def report(self) -> str:
        return f"кэш: из кэша {self.hits}, запросов к провайдеру {self.misses}"
