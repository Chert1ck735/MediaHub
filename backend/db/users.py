import uuid
from datetime import datetime
from typing import Optional, TYPE_CHECKING

from sqlalchemy import CheckConstraint, String, ForeignKey, Enum, DateTime, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db import Base, TimestampMixin, UserRole
from backend.db.enums import UserStatus

if TYPE_CHECKING:
    from backend.db.organizations import Organization
    from backend.db.posts import Post
    from backend.db.user_groups import UserGroup

class User(Base, TimestampMixin):
    __tablename__ = "users"

    __table_args__ = (
        # Цель для составных FK из user_group_members: гарантирует на уровне БД,
        # что участник группы и сама группа принадлежат одной организации
        # (иначе это было бы обещание сервисного слоя).
        UniqueConstraint("organization_id", "id", name="uq_users_org_id"),
        # email нормализуется в lowercase — пусть это обеспечивает БД, а не
        # только приложение: уникальность email иначе обходится регистром.
        CheckConstraint("email = lower(email)", name="ck_users_email_lowercase"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4
    )

    first_name: Mapped[str] = mapped_column(String(120), nullable=False)
    last_name: Mapped[str] = mapped_column(String(120), nullable=False)

    email: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        nullable=False,
        index=True
    )

    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)

    role: Mapped[UserRole] = mapped_column(
        "primary_role",
        Enum(UserRole, name="user_role_enum", create_type=False),
        nullable=False,
        default=UserRole.minion,
    )

    status: Mapped[UserStatus] = mapped_column(
        Enum(UserStatus, name="user_status_enum", create_type=False),
        nullable=False,
        default=UserStatus.active
    )

    organization_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("organizations.id", ondelete="SET NULL"),
        nullable=True
    )

    last_login_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True
    )

    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True
    )

    updated_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True
    )

    organization: Mapped[Optional["Organization"]] = relationship(
        "Organization",
        back_populates="users"
    )

    posts: Mapped[list["Post"]] = relationship("Post", back_populates="author")

    groups: Mapped[list["UserGroup"]] = relationship(
        "UserGroup",
        secondary="user_group_members",
        back_populates="members",
        viewonly=True,
    )

    @property
    def full_name(self) -> str:
        """ФИО одной строкой. Раньше это была колонка ``name``; теперь
        производное значение — чтобы имя не расходилось с first/last_name."""
        return f"{self.first_name} {self.last_name}".strip()
