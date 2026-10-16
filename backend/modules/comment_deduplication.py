"""Shared duplicate detection for comments imported from social networks."""

from __future__ import annotations

import unicodedata
import uuid
from dataclasses import dataclass, field
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.comments import Comment


def normalize_comment_text(text: str) -> str:
    """Устойчивое представление текста — только для сравнения на дубли."""

    return " ".join(unicodedata.normalize("NFC", text).split())


def comment_dedup_key(
    author_external_id: str | None,
    text: str,
) -> tuple[str, str] | None:
    """Ключ дубля или ``None``, если автора определить не удалось."""

    author = str(author_external_id or "").strip()
    normalized_text = normalize_comment_text(text)
    if not author or not normalized_text:
        return None
    return author, normalized_text


@dataclass
class CommentDedupState:
    """Известные комментарии одной публикации."""

    by_external_id: dict[str, uuid.UUID] = field(default_factory=dict)
    by_author_and_text: dict[tuple[str, str], uuid.UUID] = field(default_factory=dict)
    logically_deleted: int = 0

    def duplicate_id(
        self,
        *,
        external_id: str,
        author_external_id: str | None,
        text: str,
    ) -> uuid.UUID | None:
        known_external = self.by_external_id.get(external_id)
        if known_external is not None:
            return known_external
        key = comment_dedup_key(author_external_id, text)
        return self.by_author_and_text.get(key) if key is not None else None

    def remember(
        self,
        *,
        comment_id: uuid.UUID,
        external_id: str,
        author_external_id: str | None,
        text: str,
    ) -> None:
        self.by_external_id[external_id] = comment_id
        key = comment_dedup_key(author_external_id, text)
        if key is not None:
            self.by_author_and_text.setdefault(key, comment_id)


def build_comment_dedup_state(comments: Iterable[Comment]) -> CommentDedupState:
    """Собирает состояние и скрывает активные дубли, уже лежащие в базе.

    Строки должны идти так, чтобы оставляемая была первой. Прямые ответы на
    скрытые дубли переводятся на оставленную строку — иначе чистка утянула бы
    за собой нормальные ответы.
    """

    rows = list(comments)
    state = CommentDedupState()
    replacements: dict[uuid.UUID, uuid.UUID] = {}

    for comment in rows:
        external_id = str(comment.external_id or "").strip()
        if comment.is_deleted:
            continue

        key = comment_dedup_key(comment.author_external_id, comment.text)
        retained_id = state.by_author_and_text.get(key) if key is not None else None
        if retained_id is not None:
            comment.is_deleted = True
            replacements[comment.id] = retained_id
            state.logically_deleted += 1
            if external_id:
                state.by_external_id[external_id] = retained_id
            continue

        if external_id:
            state.by_external_id.setdefault(external_id, comment.id)
        if key is not None:
            state.by_author_and_text[key] = comment.id

    # A deleted network row must remain known, otherwise a later fetch would
    # insert it again. Prefer its retained active twin when one exists.
    for comment in rows:
        external_id = str(comment.external_id or "").strip()
        if not external_id or external_id in state.by_external_id:
            continue
        key = comment_dedup_key(comment.author_external_id, comment.text)
        state.by_external_id[external_id] = (
            state.by_author_and_text.get(key, comment.id) if key is not None else comment.id
        )

    for comment in rows:
        retained_parent = replacements.get(comment.parent_comment_id)
        if retained_parent is not None and retained_parent != comment.id:
            comment.parent_comment_id = retained_parent

    return state


async def load_comment_dedup_state(
    db: AsyncSession,
    publication_id: uuid.UUID,
) -> CommentDedupState:
    """Читает одну публикацию и убирает уже сохранённые активные дубли."""

    result = await db.execute(
        select(Comment)
        .where(Comment.publication_id == publication_id)
        .order_by(
            Comment.parent_comment_id.is_not(None),
            Comment.comment_date.asc().nulls_last(),
            Comment.created_at.asc(),
            Comment.id.asc(),
        )
    )
    return build_comment_dedup_state(result.scalars().all())
