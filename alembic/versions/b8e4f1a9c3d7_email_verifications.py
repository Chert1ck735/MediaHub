"""email_verifications: коды подтверждения почты

Revision ID: b8e4f1a9c3d7
Revises: a7f3c9d1e2b4
Create Date: 2026-07-14 10:00:00.000000

Раньше подтверждение почты жило в localStorage браузера, поэтому серверной
таблицы не было вовсе. Теперь код существует только на сервере — и только в
виде хеша.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'b8e4f1a9c3d7'
down_revision: Union[str, Sequence[str], None] = 'a7f3c9d1e2b4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'email_verifications',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        # Одна активная проверка на адрес: повторная отправка перезаписывает код.
        sa.Column('email', sa.String(255), nullable=False),
        sa.Column('code_hash', sa.String(255), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        # Без счётчика попыток шестизначный код перебирается скриптом за минуты.
        sa.Column('attempts', sa.Integer(), nullable=False, server_default='0'),
        # Cooldown между отправками — иначе форма станет спам-шлюзом.
        sa.Column(
            'last_sent_at',
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column('verified_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            'updated_at',
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint('email', name='uq_email_verifications_email'),
    )
    op.create_index(
        'ix_email_verifications_email', 'email_verifications', ['email']
    )


def downgrade() -> None:
    op.drop_index('ix_email_verifications_email', table_name='email_verifications')
    op.drop_table('email_verifications')
