"""Store source description and locality on public social links.

Revision ID: d1e3f5a7b9c0
Revises: c0d2e3f4a5b6
"""

from alembic import op


revision = "d1e3f5a7b9c0"
down_revision = "c0d2e3f4a5b6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Some production databases received these columns before Alembic recorded
    # this revision. Keep the migration safe for both drifted and clean schemas.
    op.execute(
        "ALTER TABLE public_social_links "
        "ADD COLUMN IF NOT EXISTS source_description TEXT"
    )
    op.execute(
        "ALTER TABLE public_social_links "
        "ADD COLUMN IF NOT EXISTS source_locality VARCHAR(255)"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE public_social_links "
        "DROP COLUMN IF EXISTS source_locality"
    )
    op.execute(
        "ALTER TABLE public_social_links "
        "DROP COLUMN IF EXISTS source_description"
    )
