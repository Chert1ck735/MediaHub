"""Приглашения: одноразовая ссылка для установки пароля.

Админ заводит пользователя — тот получает письмо со ссылкой и задаёт себе
пароль. До этого войти он не может: пароль у него случайный (см.
``UserService.create_user``), и узнать его неоткуда.

Отличия от ``email_verifications`` (кода регистрации), из-за которых это
отдельная таблица, а не переиспользование той:

* привязка к ПОЛЬЗОВАТЕЛЮ, а не к адресу: приглашение теряет смысл вместе с
  ним, поэтому FK с CASCADE;
* токен длинный и уходит в ссылку, а не шестизначный код для ручного ввода —
  подбирать его бессмысленно, значит счётчик попыток не нужен;
* живёт днями, а не минутами: человек может открыть почту не сразу.

Хранится ХЕШ токена: дамп БД не должен позволять зайти под чужой учёткой.
"""
import uuid
from datetime import datetime
from typing import Optional, TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from backend.db.users import User


class Invitation(Base, TimestampMixin):
    __tablename__ = "invitations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    # Одно активное приглашение на пользователя: повторная отправка
    # перезаписывает токен, а не плодит живые ссылки.
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )

    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)

    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    # Когда письмо ушло в последний раз — для cooldown повторной отправки.
    last_sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    # Кто пригласил. NULL — приглашающий уже удалён; запись должна это пережить.
    invited_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    user: Mapped["User"] = relationship("User", foreign_keys=[user_id])
