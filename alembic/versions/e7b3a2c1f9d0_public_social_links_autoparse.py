"""Автопарсер: флаг и метка последней проверки на public_social_links

Revision ID: e7b3a2c1f9d0
Revises: c9d5e2f7a1b3
Create Date: 2026-07-15 10:00:00.000000

Две новые колонки для фонового автопарсера комментариев:
    autoparse_enabled  — гонять ли по ссылке ежедневный ingest (default true);
    last_autoparse_at  — когда воркер последний раз ПРОВЕРЯЛ ссылку на дифф.

Обе nullable/со server_default, поэтому миграция безопасна на живой таблице
и не требует бэкапа существующих строк.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e7b3a2c1f9d0"
down_revision: Union[str, Sequence[str], None] = "c9d5e2f7a1b3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "public_social_links",
        sa.Column(
            "autoparse_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )
    op.add_column(
        "public_social_links",
        sa.Column(
            "last_autoparse_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("public_social_links", "last_autoparse_at")
    op.drop_column("public_social_links", "autoparse_enabled")
