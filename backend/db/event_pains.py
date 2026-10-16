"""M:M связь между событиями (events) и темами обсуждений (pains).

Одно событие может покрывать несколько болей (встреча с аудиторией в Зыково
затрагивает Дороги + ЖКХ + Соц.сферу). Одна боль может разгребаться серией
событий (штаб -> план -> отчёт). Эта таблица — мост.

Архитектурный смысл: пост рассказывает о событии, событие адресует боли.
Так замыкается цикл "видим боль -> реагируем событием -> освещаем постом".
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.base import Base


class EventPain(Base):
    __tablename__ = "event_pains"

    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("events.id", ondelete="CASCADE"),
        primary_key=True,
    )
    pain_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("pains.id", ondelete="CASCADE"),
        primary_key=True,
    )
    # 'addresses' (адресует боль), 'affects' (затрагивает), 'resolves' (закрывает).
    # Пока в UI используется только addresses; остальное — задел на будущее.
    relation_type: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="addresses"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
