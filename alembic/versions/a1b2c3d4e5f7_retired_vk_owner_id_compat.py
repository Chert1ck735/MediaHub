"""Compatibility tombstone for the reverted vk_owner_id revision.

Revision ID: a1b2c3d4e5f7
Revises: a8d2f6c4b9e1

The original revision could have been recorded in production before the
feature was reverted and its migration file was deleted.  Keep the revision
resolvable without reintroducing the retired column on clean databases.
"""
from typing import Sequence, Union


revision: str = "a1b2c3d4e5f7"
down_revision: Union[str, Sequence[str], None] = "a8d2f6c4b9e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
