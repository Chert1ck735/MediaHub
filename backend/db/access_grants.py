"""Выданные права (grants).

Модель ровно по ТЗ: полиморфные ``subject`` (пользователь ИЛИ группа
пользователей) и ``resource`` (сообщество ИЛИ группа сообществ).

ВНИМАНИЕ — цена полиморфизма. ``subject_id`` и ``resource_id`` не могут иметь
настоящего FK (ссылаются в разные таблицы в зависимости от типа), поэтому БД
НЕ удалит грант вместе с пользователем/группой/сообществом и НЕ проверит, что
ссылка вообще существует и принадлежит той же организации. Это обязанность
сервисного слоя:

* ``AccessGrantService`` проверяет существование и организацию субъекта/ресурса
  при выдаче;
* при удалении пользователя, группы пользователей, сообщества или группы
  сообществ соответствующие гранты удаляются явно (см. ``purge_grants_for``).

Забыть про второй пункт — значит оставить мусорные строки. Прав они не дают
(UUID не переиспользуются), но «итоговые доступы» начнут врать по счётчикам.

Deny-правил в первом релизе нет: право есть только если найден grant.
"""
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Enum, ForeignKey, Index, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db.base import Base, TimestampMixin
from backend.db.enums import AccessResourceType, AccessSubjectType, PermissionEnum

if TYPE_CHECKING:
    from backend.db.organizations import Organization


class AccessGrant(Base, TimestampMixin):
    __tablename__ = "access_grants"

    __table_args__ = (
        # Один и тот же грант нельзя выдать дважды.
        UniqueConstraint(
            "subject_type",
            "subject_id",
            "resource_type",
            "resource_id",
            "permission",
            name="uq_access_grants_subject_resource_permission",
        ),
        # Горячий путь авторизации: «все гранты субъекта» и «все гранты ресурса».
        Index("ix_access_grants_subject", "subject_type", "subject_id"),
        Index("ix_access_grants_resource", "resource_type", "resource_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    subject_type: Mapped[AccessSubjectType] = mapped_column(
        Enum(AccessSubjectType, name="access_subject_type_enum", create_type=False),
        nullable=False,
    )
    subject_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)

    resource_type: Mapped[AccessResourceType] = mapped_column(
        Enum(AccessResourceType, name="access_resource_type_enum", create_type=False),
        nullable=False,
    )
    resource_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)

    permission: Mapped[PermissionEnum] = mapped_column(
        Enum(PermissionEnum, name="permission_enum", create_type=False),
        nullable=False,
    )

    organization: Mapped["Organization"] = relationship("Organization")
