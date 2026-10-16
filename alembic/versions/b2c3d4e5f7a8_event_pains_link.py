"""event_pains: M:M между events и pains

Revision ID: b2c3d4e5f7a8
Revises: a1b2c3d4e5f6
Create Date: 2026-05-20

Связь "событие -> боли, которые оно адресует". Используется для замыкания
цикла "боль -> событие -> пост-ответ".
"""
from typing import Sequence, Union

from alembic import op


revision: str = "b2c3d4e5f7a8"
down_revision: Union[str, Sequence[str], None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema. Идемпотентно через IF NOT EXISTS."""
    op.execute("""
        CREATE TABLE IF NOT EXISTS event_pains (
            event_id UUID NOT NULL,
            pain_id  UUID NOT NULL,
            relation_type VARCHAR(32) NOT NULL DEFAULT 'addresses',
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
            PRIMARY KEY (event_id, pain_id),
            CONSTRAINT fk_event_pains_event
                FOREIGN KEY (event_id) REFERENCES events(id) ON DELETE CASCADE,
            CONSTRAINT fk_event_pains_pain
                FOREIGN KEY (pain_id) REFERENCES pains(id) ON DELETE CASCADE
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_event_pains_pain_id ON event_pains (pain_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_event_pains_event_id ON event_pains (event_id)")


def downgrade() -> None:
    """Downgrade schema. Идемпотентно через IF EXISTS."""
    op.execute("DROP INDEX IF EXISTS ix_event_pains_event_id")
    op.execute("DROP INDEX IF EXISTS ix_event_pains_pain_id")
    op.execute("DROP TABLE IF EXISTS event_pains")
