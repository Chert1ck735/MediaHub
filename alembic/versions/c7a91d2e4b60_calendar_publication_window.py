"""Index publication windows and organization joins without blocking writes.

Revision ID: c7a91d2e4b60
Revises: f0a1b2c3d4e5
"""
from alembic import op

revision = "c7a91d2e4b60"
down_revision = "f0a1b2c3d4e5"
branch_labels = None
depends_on = None


def upgrade():
    with op.get_context().autocommit_block():
        op.execute("""
            CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_publications_calendar_window
            ON publications ((CASE
                WHEN status = 'scheduled' AND scheduled_at IS NOT NULL THEN scheduled_at
                ELSE coalesce(published_at, scheduled_at, created_at)
            END), post_id, id)
            WHERE status <> 'deleted'
        """)
        op.execute("""
            CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_posts_calendar_organization
            ON posts (organization_id, id)
        """)


def downgrade():
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_posts_calendar_organization")
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_publications_calendar_window")
