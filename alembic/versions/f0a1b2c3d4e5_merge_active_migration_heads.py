"""Merge the two heads found in the production backend image.

Revision ID: f0a1b2c3d4e5
Revises: e9f0a1b2c3d4, d1e3f5a7b9c0

The production image built from ea1bf671 reported both parent revisions as
heads.  This no-op merge restores a single upgrade target without changing
the database schema.
"""
from typing import Sequence, Union


revision: str = "f0a1b2c3d4e5"
down_revision: Union[str, Sequence[str], None] = (
    "e9f0a1b2c3d4",
    "d1e3f5a7b9c0",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
