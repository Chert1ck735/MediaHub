"""Public and organization municipality names

Revision ID: d8e9f0a1b2c3
Revises: c0d2e3f4a5b6
Create Date: 2026-08-27

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d8e9f0a1b2c3"
down_revision: Union[str, Sequence[str], None] = "c0d2e3f4a5b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "organizations",
        sa.Column("municipality_name", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "publics",
        sa.Column("municipality_name", sa.String(length=255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("publics", "municipality_name")
    op.drop_column("organizations", "municipality_name")
