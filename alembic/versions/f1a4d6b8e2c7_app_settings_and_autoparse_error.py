"""Глобальные настройки (app_settings) + last_autoparse_error на ссылках

Revision ID: f1a4d6b8e2c7
Revises: e7b3a2c1f9d0
Create Date: 2026-07-16 10:00:00.000000

Две вещи:
    * таблица app_settings (key/value) — рантайм-настройки, которые правит
      админ (сейчас: период автопарсера);
    * колонка public_social_links.last_autoparse_error — текст последней ошибки
      автопарсера по ссылке для «состояния данных по площадкам».

Обе части аддитивны и безопасны на живой БД.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f1a4d6b8e2c7"
down_revision: Union[str, Sequence[str], None] = "e7b3a2c1f9d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "app_settings",
        sa.Column("key", sa.String(length=128), primary_key=True),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.add_column(
        "public_social_links",
        sa.Column("last_autoparse_error", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("public_social_links", "last_autoparse_error")
    op.drop_table("app_settings")
