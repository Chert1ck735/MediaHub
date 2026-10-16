"""Пул ключей Яндекс-геокодера с суточным лимитом на каждый.

У бесплатного ключа 1000 запросов в сутки, и на разовом добое базы этого мало:
переразметить 7000 адресов одним ключом — почти две недели. Пул позволяет
держать несколько ключей и переходить на следующий, когда текущий выбрал свою
норму или начал отвечать отказом.

Норма на ключ (``YANDEX_DAILY_BUDGET``) специально ниже тысячи: у Яндекса
блокировка наступает раньше формального лимита, и упереться в неё — значит
потерять ключ до конца суток.

Счётчики лежат в файле рядом с geo-кэшем, поэтому переживают перезапуск и общие
для всех воркеров процесса. Сутки считаются по UTC — так же, как квота у самого
Яндекса.
"""
from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path

from backend.app.config import settings

logger = logging.getLogger(__name__)

_lock = threading.Lock()


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _state_path() -> Path:
    return Path(settings.GEO_CACHE_PATH).with_name("geo_key_usage.json")


_runtime_keys: list[str] = []


def set_runtime_keys(keys: list[str]) -> None:
    """Ключи из БД. Геокодер синхронный, ходить из него в базу нельзя, поэтому
    задача геокодинга загружает список один раз на старте и кладёт его сюда."""
    global _runtime_keys
    _runtime_keys = [key.strip() for key in keys if key.strip()]


def configured_keys() -> list[str]:
    """Ключи из настроек: список через запятую, одиночный ключ — частный случай."""
    if _runtime_keys:
        return list(_runtime_keys)
    raw = getattr(settings, "YANDEX_GEOCODER_KEYS", "") or ""
    keys = [key.strip() for key in raw.split(",") if key.strip()]
    single = (getattr(settings, "YANDEX_GEOCODER_KEY", "") or "").strip()
    if single and single not in keys:
        keys.insert(0, single)
    return keys


def _load() -> dict:
    path = _state_path()
    if not path.exists():
        return {}
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return state if state.get("date") == _today() else {}


def _save(state: dict) -> None:
    state["date"] = _today()
    path = _state_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    except OSError as error:  # noqa: BLE001 — счётчик не повод ронять геокодинг
        logger.warning("Не удалось сохранить счётчик ключей геокодера: %s", error)


def take_key() -> str | None:
    """Ключ, у которого на сегодня остался запас. None — все выбраны."""
    keys = configured_keys()
    if not keys:
        return None
    budget = int(getattr(settings, "YANDEX_DAILY_BUDGET", 950) or 950)
    with _lock:
        state = _load()
        used = state.setdefault("used", {})
        for key in keys:
            if used.get(key, 0) < budget and not state.get("blocked", {}).get(key):
                return key
    logger.warning("Все ключи Яндекс-геокодера выбрали суточную норму (%s)", budget)
    return None


def note_request(key: str) -> None:
    with _lock:
        state = _load()
        used = state.setdefault("used", {})
        used[key] = used.get(key, 0) + 1
        _save(state)


def note_rejected(key: str) -> None:
    """Ключ отвечает отказом — до конца суток его не трогаем."""
    with _lock:
        state = _load()
        state.setdefault("blocked", {})[key] = True
        _save(state)
    logger.warning("Ключ Яндекс-геокодера отклонён, перехожу на следующий")


def has_capacity() -> bool:
    """Остался ли хоть один ключ с запасом на сегодня.

    Нужна задачам догеокодинга: когда норма выбрана, геокодер молча возвращает
    пусто, и без этой проверки кейс записался бы в кэш как отказ, хотя его не
    спрашивали. Такой ложный отказ потом пропускается как уже проверенный.
    """
    return take_key() is not None


def usage() -> dict:
    """Сколько израсходовано по каждому ключу — для диагностики через API."""
    state = _load()
    budget = int(getattr(settings, "YANDEX_DAILY_BUDGET", 950) or 950)
    used = state.get("used", {})
    blocked = state.get("blocked", {})
    return {
        "date": _today(),
        "budget_per_key": budget,
        "keys": [
            {
                "key": f"…{key[-6:]}",
                "used": used.get(key, 0),
                "left": max(0, budget - used.get(key, 0)),
                "blocked": bool(blocked.get(key)),
            }
            for key in configured_keys()
        ],
    }
