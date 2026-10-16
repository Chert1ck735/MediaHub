import uuid
from typing import Optional, TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db import TimestampMixin, Base, Module

if TYPE_CHECKING:
    from backend.db.organizations import Organization
    from backend.db.regions import Region
    from backend.db.public_social_links import PublicSocialLink
    from backend.db.modules import Module


class Public(TimestampMixin, Base):
    """
    Сущность аналитической площадки (паблика), за которой ведётся мониторинг.
    Паблик является логической сущностью верхнего уровня и может содержать
    ссылки на сообщества в различных социальных сетях через таблицу
    PublicSocialLink.
    """

    __tablename__ = "publics"

    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "name",
            name="uq_publics_org_name"
        ),
        # Цель для составного FK из community_group_members: гарантирует, что
        # сообщество и группа сообществ принадлежат одной организации.
        UniqueConstraint(
            "organization_id",
            "id",
            name="uq_publics_org_id"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(
            "organizations.id",
            ondelete="CASCADE"
        ),
        nullable=False,
        index=True
    )

    region_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey(
            "regions.id",
            ondelete="SET NULL"
        ),
        nullable=True
    )

    municipality_name: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True
    )

    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False
    )

    code: Mapped[Optional[str]] = mapped_column(
        String(128),
        nullable=True
    )

    description: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True
    )

    audience_description: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True
    )

    goal: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True
    )

    # Применимые категории болей; NULL = все (зона не задана/муниципалитет).
    applicable_categories: Mapped[Optional[list[str]]] = mapped_column(
        ARRAY(String),
        nullable=True
    )

    organization: Mapped["Organization"] = relationship(
        "Organization",
        back_populates="publics"
    )

    region: Mapped[Optional["Region"]] = relationship(
        "Region"
    )

    social_links: Mapped[list["PublicSocialLink"]] = relationship(
        "PublicSocialLink",
        back_populates="public",
        cascade="all, delete-orphan"
    )

    module: Mapped[Optional["Module"]] = relationship(
        "Module",
        back_populates="public",
        uselist=False,
        cascade="all, delete-orphan"
    )
