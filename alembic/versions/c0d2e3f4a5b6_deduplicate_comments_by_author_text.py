"""Soft-delete duplicate comments written by the same author.

Revision ID: c0d2e3f4a5b6
Revises: b9c1d2e3f4a5
Create Date: 2026-08-19

Duplicates are scoped to one publication.  The oldest top-level occurrence is
retained; direct replies are reparented before duplicates are hidden, so no
comment or reply is physically deleted.
"""

from typing import Sequence, Union

from alembic import op


revision: str = "c0d2e3f4a5b6"
down_revision: Union[str, Sequence[str], None] = "b9c1d2e3f4a5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_RANKED_COMMENTS_SQL = """
    SELECT
        id,
        FIRST_VALUE(id) OVER (
            PARTITION BY
                publication_id,
                btrim(author_external_id),
                regexp_replace(btrim(text), '[[:space:]]+', ' ', 'g')
            ORDER BY
                CASE WHEN parent_comment_id IS NULL THEN 0 ELSE 1 END,
                comment_date ASC NULLS LAST,
                created_at ASC,
                id ASC
        ) AS retained_id,
        ROW_NUMBER() OVER (
            PARTITION BY
                publication_id,
                btrim(author_external_id),
                regexp_replace(btrim(text), '[[:space:]]+', ' ', 'g')
            ORDER BY
                CASE WHEN parent_comment_id IS NULL THEN 0 ELSE 1 END,
                comment_date ASC NULLS LAST,
                created_at ASC,
                id ASC
        ) AS duplicate_rank
    FROM comments
    WHERE is_deleted = false
      AND NULLIF(btrim(author_external_id), '') IS NOT NULL
      AND NULLIF(regexp_replace(btrim(text), '[[:space:]]+', ' ', 'g'), '') IS NOT NULL
"""


def upgrade() -> None:
    op.execute(
        f"""
        WITH ranked AS ({_RANKED_COMMENTS_SQL}),
        duplicates AS (
            SELECT id AS duplicate_id, retained_id
            FROM ranked
            WHERE duplicate_rank > 1
        )
        UPDATE comments AS child
        SET parent_comment_id = duplicates.retained_id,
            updated_at = now()
        FROM duplicates
        WHERE child.parent_comment_id = duplicates.duplicate_id
          AND child.id <> duplicates.retained_id
        """
    )
    op.execute(
        f"""
        WITH ranked AS ({_RANKED_COMMENTS_SQL})
        UPDATE comments AS duplicate
        SET is_deleted = true,
            updated_at = now()
        FROM ranked
        WHERE duplicate.id = ranked.id
          AND ranked.duplicate_rank > 1
        """
    )


def downgrade() -> None:
    # A previous soft deletion cannot be distinguished reliably from this data
    # cleanup.  Rows remain stored and can be restored manually if necessary.
    pass
