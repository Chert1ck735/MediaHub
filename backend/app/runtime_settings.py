"""Чтение/запись глобальных настроек, которые админ правит в рантайме.

Живут в таблице ``app_settings`` (key/value). Здесь — типизированная обёртка:
знает про конкретные ключи, парсит строки и подставляет дефолт из .env, если
строки в БД ещё нет. Так воркер и роутеры читают одно и то же значение, а не
каждый свою копию из конфига.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.config import settings as app_settings
from backend.db.app_settings import AppSetting

# Ключ периода автопарсера (в часах). Дефолт — из .env (AUTOPARSE_INTERVAL_HOURS).
AUTOPARSE_INTERVAL_HOURS_KEY = "autoparse_interval_hours"

# Разумные границы, чтобы из UI нельзя было выставить 0 или абсурдно большое.
MIN_AUTOPARSE_INTERVAL_HOURS = 1
MAX_AUTOPARSE_INTERVAL_HOURS = 24 * 30  # месяц


async def _get_raw(db: AsyncSession, key: str) -> str | None:
    return (
        await db.execute(select(AppSetting.value).where(AppSetting.key == key))
    ).scalar_one_or_none()


async def _set_raw(db: AsyncSession, key: str, value: str) -> None:
    # UPSERT: настроек по ключу максимум одна.
    stmt = (
        pg_insert(AppSetting)
        .values(key=key, value=value)
        .on_conflict_do_update(index_elements=["key"], set_={"value": value})
    )
    await db.execute(stmt)


def clamp_autoparse_interval_hours(hours: int) -> int:
    return max(MIN_AUTOPARSE_INTERVAL_HOURS, min(MAX_AUTOPARSE_INTERVAL_HOURS, int(hours)))


async def get_autoparse_interval_hours(db: AsyncSession) -> int:
    """Текущий период автопарсера в часах: из БД либо дефолт из .env."""

    raw = await _get_raw(db, AUTOPARSE_INTERVAL_HOURS_KEY)
    if raw is None:
        return app_settings.AUTOPARSE_INTERVAL_HOURS
    try:
        return clamp_autoparse_interval_hours(int(raw))
    except (TypeError, ValueError):
        return app_settings.AUTOPARSE_INTERVAL_HOURS


async def set_autoparse_interval_hours(db: AsyncSession, hours: int) -> int:
    """Сохраняет период автопарсера (с обрезкой по границам). Не коммитит —
    коммит на вызывающей стороне."""

    value = clamp_autoparse_interval_hours(hours)
    await _set_raw(db, AUTOPARSE_INTERVAL_HOURS_KEY, str(value))
    return value


# Ключи Яндекс-геокодера. Держим в БД, а не только в .env: на сервере правка
# переменных окружения требует передеплоя, а ключи меняются по мере выборки
# суточной нормы. Дефолт — из .env, чтобы существующая установка не сломалась.
YANDEX_GEOCODER_KEYS_KEY = "yandex_geocoder_keys"


async def get_yandex_geocoder_keys(db: AsyncSession) -> list[str]:
    raw = await _get_raw(db, YANDEX_GEOCODER_KEYS_KEY)
    if raw is None:
        raw = ",".join(
            part for part in (
                app_settings.YANDEX_GEOCODER_KEY,
                app_settings.YANDEX_GEOCODER_KEYS,
            ) if part
        )
    return [key.strip() for key in raw.split(",") if key.strip()]


async def set_yandex_geocoder_keys(db: AsyncSession, keys: list[str]) -> list[str]:
    """Сохраняет список ключей. Не коммитит — коммит на вызывающей стороне."""

    cleaned = [key.strip() for key in keys if key.strip()]
    await _set_raw(db, YANDEX_GEOCODER_KEYS_KEY, ",".join(cleaned))
    return cleaned
