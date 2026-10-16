"""add unique constraint pain_evidence (pain_id, comment_id)

Revision ID: e5a1b2c3d4f0
Revises: d418ae4995dd
Create Date: 2026-06-25 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'e5a1b2c3d4f0'
down_revision: Union[str, Sequence[str], None] = 'd418ae4995dd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Снимаем накопившиеся дубли evidence перед навешиванием constraint.
    # comment_id IS NULL (post-url evidence) не трогаем — там дедуп не нужен.
    op.execute(
        """
        DELETE FROM pain_evidence a
        USING pain_evidence b
        WHERE a.ctid < b.ctid
          AND a.pain_id = b.pain_id
          AND a.comment_id = b.comment_id
          AND a.comment_id IS NOT NULL
        """
    )
    op.create_unique_constraint(
        'uq_pain_evidence_pain_comment', 'pain_evidence', ['pain_id', 'comment_id']
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('uq_pain_evidence_pain_comment', 'pain_evidence', type_='unique')
