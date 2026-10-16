"""Разбор фильтра площадок из query-параметра аналитики."""
from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any, TypeAlias


PublicSocialLinkFilter: TypeAlias = uuid.UUID | Sequence[uuid.UUID] | None


def parse_public_social_link_ids(value: str | None) -> list[uuid.UUID]:
    """Парсит один UUID либо CSV-список UUID, удаляя дубли."""

    if not value:
        return []
    result: list[uuid.UUID] = []
    for item in value.split(","):
        candidate = item.strip()
        if not candidate:
            continue
        link_id = uuid.UUID(candidate)
        if link_id not in result:
            result.append(link_id)
    return result


def apply_public_social_link_filter(
    statement: Any,
    column: Any,
    link_filter: PublicSocialLinkFilter,
) -> Any:
    """Добавляет к запросу условие по одной площадке или по нескольким."""

    link_ids = normalize_public_social_link_ids(link_filter)
    if not link_ids:
        return statement
    if len(link_ids) == 1:
        return statement.where(column == link_ids[0])
    return statement.where(column.in_(link_ids))


def normalize_public_social_link_ids(
    link_filter: PublicSocialLinkFilter,
) -> list[uuid.UUID]:
    """Приводит внутренний фильтр источников к списку уникальных UUID."""

    if link_filter is None:
        return []
    if isinstance(link_filter, uuid.UUID):
        return [link_filter]
    return list(dict.fromkeys(link_filter))


def compact_public_social_link_filter(
    link_ids: Sequence[uuid.UUID],
) -> PublicSocialLinkFilter:
    """Одиночное значение для одной площадки, список — для нескольких."""

    unique_ids = list(dict.fromkeys(link_ids))
    if not unique_ids:
        return None
    return unique_ids[0] if len(unique_ids) == 1 else unique_ids
