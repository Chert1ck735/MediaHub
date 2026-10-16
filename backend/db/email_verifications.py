"""Подтверждение почты кодом из письма.

Раньше вся проверка жила в браузере: код генерировался на клиенте, его хеш
лежал в localStorage, а при недоступности почты код печатался прямо на экране.
Это не проверка — её обходил любой, кто открыл DevTools. Теперь код живёт
только на сервере, а клиент видит лишь «отправлено» / «неверно».

Одна строка на адрес: повторная отправка перезаписывает код, а не плодит записи.

Хранится ХЕШ кода, не сам код: утечка дампа БД не должна давать возможность
подтвердить чужую почту.
"""
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.base import Base, TimestampMixin


class EmailVerification(Base, TimestampMixin):
    __tablename__ = "email_verifications"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    # Нормализованный (lowercase) адрес. Уникален: одна активная проверка на почту.
    email: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        unique=True,
        index=True,
    )

    code_hash: Mapped[str] = mapped_column(String(255), nullable=False)

    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    # Счётчик неверных попыток. Без него шестизначный код перебирается за минуты.
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Когда код был отправлен в последний раз — для cooldown между отправками
    # (иначе форма превращается в бесплатный спам-шлюз по чужим адресам).
    last_sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    # Почта подтверждена. Регистрация без этой отметки не проходит.
    verified_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
