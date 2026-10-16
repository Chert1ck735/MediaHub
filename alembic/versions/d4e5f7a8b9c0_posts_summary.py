"""posts.summary: добавить колонку (синхронизация с моделью из main)

Revision ID: d4e5f7a8b9c0
Revises: c3d4e5f7a8b9
Create Date: 2026-05-22

В main коллеги переинициализировали init-миграцию (89bee583b4ea_init) и
добавили туда posts.summary (Text, nullable). При мердже мы оставили
свою цепочку миграций (f3410cd5e9c7 + 3 поверх) и backend/db/posts.py
из main (там новое поле summary). Эта миграция приводит БД к согласию
с моделью без переписывания init.
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text


revision: str = "d4e5f7a8b9c0"
down_revision: Union[str, Sequence[str], None] = "c3d4e5f7a8b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(text("ALTER TABLE posts ADD COLUMN IF NOT EXISTS summary TEXT"))


def downgrade() -> None:
    op.execute(text("ALTER TABLE posts DROP COLUMN IF EXISTS summary"))
