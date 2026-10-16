"""invitations: одноразовая ссылка для установки пароля

Revision ID: c9d5e2f7a1b3
Revises: b8e4f1a9c3d7
Create Date: 2026-07-14 12:00:00.000000

Раньше приглашений не было вовсе: админ заводил пользователя со случайным
паролем, письма не уходило, и войти тот не мог никак.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'c9d5e2f7a1b3'
down_revision: Union[str, Sequence[str], None] = 'b8e4f1a9c3d7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'invitations',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        # Одно активное приглашение на пользователя: повторная отправка
        # перезаписывает токен, а не плодит живые ссылки.
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        # Хеш, не сам токен: дамп БД не должен давать вход под чужой учёткой.
        sa.Column('token_hash', sa.String(64), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            'last_sent_at',
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column('invited_by', postgresql.UUID(as_uuid=True), nullable=True),
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
        # Приглашение теряет смысл вместе с пользователем.
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        # А вот запись должна пережить удаление того, КТО пригласил.
        sa.ForeignKeyConstraint(['invited_by'], ['users.id'], ondelete='SET NULL'),
        sa.UniqueConstraint('user_id', name='uq_invitations_user'),
        sa.UniqueConstraint('token_hash', name='uq_invitations_token_hash'),
    )
    op.create_index('ix_invitations_user_id', 'invitations', ['user_id'])


def downgrade() -> None:
    op.drop_index('ix_invitations_user_id', table_name='invitations')
    op.drop_table('invitations')
