"""modules.public_id: добавить колонку в БД (модель была, БД не имела)

Revision ID: c3d4e5f7a8b9
Revises: b2c3d4e5f7a8
Create Date: 2026-05-22

Контекст:
SQLAlchemy-модель Module имеет public_id (FK на publics, NOT NULL, UNIQUE),
а в БД эта колонка отсутствовала с момента init-миграции — schema_drift
обнаружил расхождение. Любой INSERT в modules (через /api/modules/create)
падал UndefinedColumn до этой правки.

Дизайн: колонка добавляется как NULLable; если в таблице ничего нет или
все существующие строки заполнены — миграция сразу ставит NOT NULL.
Иначе оставляем NULLable + warning в stderr миграции, чтобы оператор
вручную доделал backfill и SET NOT NULL.
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text


revision: str = "c3d4e5f7a8b9"
down_revision: Union[str, Sequence[str], None] = "b2c3d4e5f7a8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema. Идемпотентно."""
    op.execute("""
        ALTER TABLE modules
        ADD COLUMN IF NOT EXISTS public_id UUID
            REFERENCES publics(id) ON DELETE CASCADE
    """)
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_modules_public_id
        ON modules (public_id)
    """)

    conn = op.get_bind()
    null_rows = conn.execute(text(
        "SELECT COUNT(*) FROM modules WHERE public_id IS NULL"
    )).scalar()
    if null_rows == 0:
        op.execute("ALTER TABLE modules ALTER COLUMN public_id SET NOT NULL")
    else:
        print(
            f"[migration c3d4e5f7a8b9] modules has {null_rows} rows without public_id; "
            f"keeping the column NULLable. После ручного UPDATE сделайте: "
            f"ALTER TABLE modules ALTER COLUMN public_id SET NOT NULL"
        )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP INDEX IF EXISTS uq_modules_public_id")
    op.execute("ALTER TABLE modules DROP COLUMN IF EXISTS public_id")
