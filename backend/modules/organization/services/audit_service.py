"""Аудит изменений в настройках организации.

Пишет в ``audit_log`` до/после каждого изменения пользователей, групп, прав и
импорта.

Секреты в аудит не попадают: ``_SENSITIVE_FIELDS`` вырезаются из снимков.
Полагаться на «вызывающий сам не передаст пароль» нельзя — снимок обычно
строится из ``__dict__``/схемы целиком, и любое новое поле уедет в лог само.
Содержимое загруженных файлов в аудит тоже не пишем — только сводку по строкам.
"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.audit_log import AuditLog

# Никогда не покидают процесс: даже в хешированном виде им в аудите не место.
_SENSITIVE_FIELDS = frozenset(
    {
        "password",
        "password_hash",
        "raw_password",
        "token",
        "access_token",
        "refresh_token",
        "secret",
        "file",
        "file_content",
        "content",
    }
)


def scrub(data: dict[str, Any] | None) -> dict[str, Any] | None:
    """Убирает секреты из снимка и приводит значения к JSON-совместимым."""
    if data is None:
        return None
    out: dict[str, Any] = {}
    for key, value in data.items():
        if key in _SENSITIVE_FIELDS:
            continue
        if isinstance(value, uuid.UUID):
            out[key] = str(value)
        elif hasattr(value, "value"):  # Enum
            out[key] = value.value
        elif isinstance(value, (str, int, float, bool, type(None), list, dict)):
            out[key] = value
        else:
            out[key] = str(value)
    return out


class AuditService:
    """Пишет записи аудита в текущую транзакцию (без своего commit).

    Коммитит вызывающий: запись аудита обязана попасть в БД той же транзакцией,
    что и само изменение, иначе можно получить «изменение без следа» или
    «след без изменения».
    """

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    def record(
        self,
        *,
        organization_id: uuid.UUID,
        actor_user_id: uuid.UUID | None,
        entity_type: str,
        action: str,
        entity_id: uuid.UUID | None = None,
        before: dict[str, Any] | None = None,
        after: dict[str, Any] | None = None,
    ) -> None:
        self._db.add(
            AuditLog(
                organization_id=organization_id,
                actor_user_id=actor_user_id,
                entity_type=entity_type,
                entity_id=entity_id,
                action=action,
                before_data=scrub(before),
                after_data=scrub(after),
            )
        )
