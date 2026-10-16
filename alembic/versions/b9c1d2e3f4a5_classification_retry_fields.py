"""Ретраи классификации: attempts и next_attempt_at на comment_analysis

Revision ID: b9c1d2e3f4a5
Revises: a8d2f6c4b9e1
Create Date: 2026-08-12

Раньше запись после исчерпания LLM-ретраев уходила в failed навсегда —
любой сбой сети выжигал дыру в данных до ручного reclassify_all. Теперь:
- classification_attempts — сколько батч-попыток исчерпано;
- next_attempt_at — когда воркер возьмёт запись снова (NULL у failed =
  упало окончательно, после MAX_CLASSIFY_ATTEMPTS).

Backfill: старые failed (attempts=0) получают next_attempt_at=now() —
право на новый цикл попыток после поднятия LLM.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b9c1d2e3f4a5"
down_revision: Union[str, Sequence[str], None] = "a8d2f6c4b9e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE comment_analysis "
        "ADD COLUMN IF NOT EXISTS classification_attempts INTEGER NOT NULL DEFAULT 0"
    )
    op.execute(
        "ALTER TABLE comment_analysis "
        "ADD COLUMN IF NOT EXISTS next_attempt_at TIMESTAMPTZ"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_comment_analysis_next_attempt_at "
        "ON comment_analysis (next_attempt_at) WHERE next_attempt_at IS NOT NULL"
    )
    op.execute(
        """
        UPDATE comment_analysis
        SET next_attempt_at = now()
        WHERE classification_state = 'failed'
          AND next_attempt_at IS NULL
          AND classification_attempts = 0
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_comment_analysis_next_attempt_at")
    op.execute("ALTER TABLE comment_analysis DROP COLUMN IF EXISTS next_attempt_at")
    op.execute("ALTER TABLE comment_analysis DROP COLUMN IF EXISTS classification_attempts")
