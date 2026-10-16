"""Аудит изменений в настройках организации.

Отдельная таблица от существующего ``action_logs``: у того другая форма (он
про действия аналитики/ингеста), а по ТЗ нужен аудит с before/after-снимками.
Существующие таблицы не трогаем.

В ``before_data``/``after_data`` НЕЛЬЗЯ писать пароли, токены и содержимое
загруженных файлов — снимки чистит ``AuditService`` перед записью.
"""
import uuid
from datetime import datetime
from typing import Optional, TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db.base import Base

if TYPE_CHECKING:
    from backend.db.organizations import Organization
    from backend.db.users import User


class AuditLog(Base):
    __tablename__ = "audit_log"

    __table_args__ = (
        # Лента аудита организации — всегда «последние сверху».
        Index("ix_audit_log_org_created", "organization_id", "created_at"),
        # История конкретной сущности.
        Index("ix_audit_log_entity", "entity_type", "entity_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )

    # Автор действия. NULL — системное действие или пользователь уже удалён:
    # запись аудита обязана пережить удаление того, кто её породил.
    actor_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False)

    before_data: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    after_data: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    organization: Mapped["Organization"] = relationship("Organization")
    actor: Mapped[Optional["User"]] = relationship("User")
