from datetime import datetime, timezone
import uuid

from backend.db.comments import Comment
from backend.modules.comment_deduplication import (
    CommentDedupState,
    build_comment_dedup_state,
    comment_dedup_key,
    normalize_comment_text,
)


PUBLICATION_ID = uuid.uuid4()


def _comment(
    external_id: str,
    text: str,
    author: str | None,
    *,
    parent_id: uuid.UUID | None = None,
    deleted: bool = False,
) -> Comment:
    now = datetime(2026, 8, 19, tzinfo=timezone.utc)
    return Comment(
        id=uuid.uuid4(),
        publication_id=PUBLICATION_ID,
        parent_comment_id=parent_id,
        external_id=external_id,
        text=text,
        author_external_id=author,
        comment_date=now,
        parsed_at=now,
        created_at=now,
        updated_at=now,
        is_deleted=deleted,
    )


def test_normalize_comment_text_collapses_only_whitespace() -> None:
    assert normalize_comment_text("  Один\n\n и   тот же текст  ") == "Один и тот же текст"
    assert comment_dedup_key("42", "Текст") != comment_dedup_key("42", "текст")


def test_existing_duplicate_is_soft_deleted_and_its_reply_is_reparented() -> None:
    retained = _comment("100", "Один и тот же текст", "42")
    duplicate = _comment("101", "  Один\nи тот   же текст ", "42")
    reply = _comment("102", "Ответ", "77", parent_id=duplicate.id)

    state = build_comment_dedup_state([retained, duplicate, reply])

    assert retained.is_deleted is False
    assert duplicate.is_deleted is True
    assert reply.parent_comment_id == retained.id
    assert state.logically_deleted == 1
    assert state.by_external_id["101"] == retained.id


def test_different_author_or_text_is_not_a_duplicate() -> None:
    first = _comment("100", "Текст", "42")
    different_author = _comment("101", "Текст", "43")
    different_text = _comment("102", "Другой текст", "42")

    state = build_comment_dedup_state([first, different_author, different_text])

    assert state.logically_deleted == 0
    assert all(not row.is_deleted for row in (first, different_author, different_text))


def test_unknown_authors_are_not_deduplicated() -> None:
    first = _comment("100", "Текст", None)
    second = _comment("101", "Текст", None)

    state = build_comment_dedup_state([first, second])

    assert state.logically_deleted == 0
    assert second.is_deleted is False


def test_same_author_and_text_are_allowed_in_another_publication() -> None:
    first_post_comment = _comment("100", "Одинаковый текст", "42")
    second_post_comment = _comment("200", "Одинаковый текст", "42")
    second_post_comment.publication_id = uuid.uuid4()

    first_state = build_comment_dedup_state([first_post_comment])
    second_state = build_comment_dedup_state([second_post_comment])

    assert first_state.logically_deleted == 0
    assert second_state.logically_deleted == 0
    assert first_post_comment.is_deleted is False
    assert second_post_comment.is_deleted is False


def test_new_batch_duplicate_resolves_to_retained_comment() -> None:
    retained_id = uuid.uuid4()
    state = CommentDedupState()
    state.remember(
        comment_id=retained_id,
        external_id="100",
        author_external_id="42",
        text="Повтор сообщения",
    )

    assert state.duplicate_id(
        external_id="101",
        author_external_id="42",
        text="  Повтор\n сообщения ",
    ) == retained_id
    assert state.duplicate_id(
        external_id="102",
        author_external_id="43",
        text="Повтор сообщения",
    ) is None
