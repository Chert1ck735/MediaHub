"""Merge the retired vk_owner_id branch into the active migration chain.

Revision ID: e9f0a1b2c3d4
Revises: d8e9f0a1b2c3, a1b2c3d4e5f7
"""
from typing import Sequence, Union


revision: str = "e9f0a1b2c3d4"
down_revision: Union[str, Sequence[str], None] = (
    "d8e9f0a1b2c3",
    "a1b2c3d4e5f7",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
