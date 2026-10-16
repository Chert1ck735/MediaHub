from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.action_logs import ActionLog


def _normalize_details(details: dict[str, Any] | None) -> dict[str, Any]:
    if not details:
        return {}
    normalized: dict[str, Any] = {}
    for key, value in details.items():
        if isinstance(value, uuid.UUID):
            normalized[key] = str(value)
        else:
            normalized[key] = value
    return normalized


def add_action_log(
    db: AsyncSession,
    *,
    user_id: uuid.UUID | None,
    action: str,
    entity_type: str,
    entity_id: uuid.UUID | None = None,
    details: dict[str, Any] | None = None,
    ip_address: str | None = None,
) -> None:
    db.add(
        ActionLog(
            user_id=user_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            details=_normalize_details(details),
            ip_address=ip_address,
        )
    )
