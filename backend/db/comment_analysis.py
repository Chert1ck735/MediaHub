import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Boolean, Float, ForeignKey, Enum, Integer, String, Text, JSON, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db.base import Base, TimestampMixin
from backend.db.enums import SentimentEnum, RelevanceEnum

if TYPE_CHECKING:
    from backend.db.comments import Comment


class CommentAnalysis(Base, TimestampMixin):
    __tablename__ = "comment_analysis"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    comment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("comments.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )

    sentiment: Mapped[Optional[SentimentEnum]] = mapped_column(
        Enum(SentimentEnum, name="sentiment_enum"),
        nullable=True
    )

    relevance: Mapped[RelevanceEnum] = mapped_column(
        Enum(RelevanceEnum, name="relevance_enum"),
        nullable=False,
        default=RelevanceEnum.relevant,
    )

    confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    topics: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    model_version: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)

    analyzed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    author_type: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    message_type: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    is_official_response: Mapped[bool] = mapped_column(default=False)
    hierarchy: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    entities: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    # classification_source — кто реально классифицировал запись.
    # Допустимые значения:
    #   "llm"            — LLM назвал валидную содержательную category;
    #   "llm_other"      — LLM сам сказал "Другое" (валидный ответ модели);
    #   "rule_based"     — категория поднята из keyword-rules;
    #   "needs_review"   — rule-based relevant без категории, можно докрутить LLM;
    #   "llm_needs_review" — LLM уже попробовала, но category не вытащилась;
    #   "llm_manual"     — категорию назначили вручную в настройках;
    #   "fallback"       — irrelevant / служебный ответ;
    #   "unknown"        — старые записи без указания источника.
    classification_source: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, index=True
    )

    # classification_state — состояние очереди классификации.
    # "pending"     — ждёт LLM-классификатор;
    # "processing"  — взят worker'ом;
    # "done"        — успешно классифицирован;
    # "failed"      — LLM упал N раз подряд, оставлен с rule_based fallback.
    classification_state: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="done", default="done", index=True
    )

    # Ретраи упавшей классификации: сколько батч-попыток исчерпано и когда
    # можно пробовать снова. failed + next_attempt_at IS NULL = упало окончательно.
    classification_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0", default=0
    )
    next_attempt_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # candidates — top-N вариантов от LLM с confidence.
    # Структура: [{"category": ..., "subcategory": ..., "confidence": 0.78}, ...]
    # Нужно для confidence-based routing и UI «показать второй вариант».
    candidates: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)

    # needs_review — флаг, требующий ручного ревью.
    # Выставляется автоматически (top-1 confidence < порога, ambiguous, и т.п.)
    # или вручную из UI.
    needs_review: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false", default=False, index=True
    )

    comment: Mapped["Comment"] = relationship("Comment", back_populates="analysis")
