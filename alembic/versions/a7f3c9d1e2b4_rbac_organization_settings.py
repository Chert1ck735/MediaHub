"""RBAC: роли, группы пользователей и сообществ, гранты, аудит

Revision ID: a7f3c9d1e2b4
Revises: f1a2b3c4d5e6
Create Date: 2026-07-13 12:00:00.000000

Написана вручную: autogenerate не видит ни смену значений enum, ни
переименование колонок (для ``users.name`` он бы выдал drop+add и потерял ФИО).

Маппинг ролей (необратим в части ``editor``):
    system_admin -> superadmin
    admin        -> admin
    editor       -> minion   ← сливается с viewer
    viewer       -> minion
Право публиковать, которое раньше подразумевала роль ``editor``, теперь
выдаётся явным грантом ``create_post`` — при откате различие editor/viewer
восстановить неоткуда, все станут ``viewer``.

Маппинг статусов: banned -> blocked, добавлен invited.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'a7f3c9d1e2b4'
down_revision: Union[str, Sequence[str], None] = 'f1a2b3c4d5e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _swap_enum(
    table: str,
    column: str,
    old_type: str,
    new_type: str,
    new_values: tuple[str, ...],
    mapping: dict[str, str],
    default: str,
) -> None:
    """Меняет набор значений enum'а с переносом данных.

    Значения из enum'а нельзя удалить через ALTER TYPE, поэтому создаём новый
    тип, переводим колонку с USING-маппингом, старый тип удаляем и
    переименовываем новый на его место.
    """
    values_sql = ", ".join(f"'{v}'" for v in new_values)
    cases = " ".join(f"WHEN '{old}' THEN '{new}'" for old, new in mapping.items())

    op.execute(f"CREATE TYPE {new_type} AS ENUM ({values_sql})")
    # DROP DEFAULT обязателен: старый default имеет старый тип и не приводится.
    op.execute(f"ALTER TABLE {table} ALTER COLUMN {column} DROP DEFAULT")
    op.execute(
        f"ALTER TABLE {table} ALTER COLUMN {column} TYPE {new_type} "
        f"USING (CASE {column}::text {cases} END)::{new_type}"
    )
    op.execute(f"DROP TYPE {old_type}")
    op.execute(f"ALTER TYPE {new_type} RENAME TO {old_type}")
    op.execute(f"ALTER TABLE {table} ALTER COLUMN {column} SET DEFAULT '{default}'")


def upgrade() -> None:
    bind = op.get_bind()

    # ── users: name -> first_name / last_name ────────────────────────────────
    op.add_column('users', sa.Column('first_name', sa.String(120), nullable=True))
    op.add_column('users', sa.Column('last_name', sa.String(120), nullable=True))

    # ФИО режем по первому пробелу: "Иван Тихонов" -> ("Иван", "Тихонов").
    # Имя без пробела -> фамилия пустая (не NULL): врать выдуманной фамилией хуже.
    op.execute(
        """
        UPDATE users SET
            first_name = COALESCE(NULLIF(split_part(btrim(name), ' ', 1), ''), 'Пользователь'),
            last_name  = COALESCE(
                NULLIF(btrim(substr(btrim(name), length(split_part(btrim(name), ' ', 1)) + 2)), ''),
                ''
            )
        """
    )
    op.alter_column('users', 'first_name', nullable=False)
    op.alter_column('users', 'last_name', nullable=False)
    op.drop_column('users', 'name')

    # ── email в lowercase + CHECK ────────────────────────────────────────────
    # Схлопывание регистра может породить дубль там, где раньше его не было
    # (Ivan@x.ru и ivan@x.ru). Молча убить одну строку нельзя — падаем внятно.
    collisions = bind.execute(
        sa.text(
            "SELECT lower(email) AS e, count(*) AS n FROM users "
            "GROUP BY 1 HAVING count(*) > 1"
        )
    ).fetchall()
    if collisions:
        listed = ", ".join(f"{row.e} ({row.n})" for row in collisions)
        raise RuntimeError(
            "Миграция остановлена: приведение email к lowercase создаст дубликаты — "
            f"{listed}. Устраните дубли вручную и повторите upgrade."
        )
    op.execute("UPDATE users SET email = lower(email) WHERE email <> lower(email)")
    op.create_check_constraint('ck_users_email_lowercase', 'users', 'email = lower(email)')

    # ── роли и статусы ──────────────────────────────────────────────────────
    _swap_enum(
        table='users',
        column='primary_role',
        old_type='user_role_enum',
        new_type='user_role_enum_new',
        new_values=('superadmin', 'admin', 'minion'),
        mapping={
            'system_admin': 'superadmin',
            'admin': 'admin',
            'editor': 'minion',
            'viewer': 'minion',
        },
        default='minion',
    )
    _swap_enum(
        table='users',
        column='status',
        old_type='user_status_enum',
        new_type='user_status_enum_new',
        new_values=('active', 'blocked', 'invited'),
        mapping={'active': 'active', 'banned': 'blocked'},
        default='active',
    )

    # ── цели для составных FK (принадлежность одной организации) ─────────────
    op.create_unique_constraint('uq_users_org_id', 'users', ['organization_id', 'id'])
    op.create_unique_constraint('uq_publics_org_id', 'publics', ['organization_id', 'id'])

    # ── новые enum'ы ────────────────────────────────────────────────────────
    op.execute(
        "CREATE TYPE permission_enum AS ENUM "
        "('view_community', 'create_post', 'manage_community', 'view_organization_analytics')"
    )
    op.execute("CREATE TYPE access_subject_type_enum AS ENUM ('user', 'user_group')")
    op.execute("CREATE TYPE access_resource_type_enum AS ENUM ('community', 'community_group')")

    permission_enum = postgresql.ENUM(name='permission_enum', create_type=False)
    subject_enum = postgresql.ENUM(name='access_subject_type_enum', create_type=False)
    resource_enum = postgresql.ENUM(name='access_resource_type_enum', create_type=False)

    # ── группы пользователей ────────────────────────────────────────────────
    op.create_table(
        'user_groups',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.UniqueConstraint('organization_id', 'name', name='uq_user_groups_org_name'),
        sa.UniqueConstraint('organization_id', 'id', name='uq_user_groups_org_id'),
    )
    op.create_index('ix_user_groups_organization_id', 'user_groups', ['organization_id'])

    op.create_table(
        'user_group_members',
        sa.Column('user_group_id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True), nullable=False),
        # Составные FK — гарантия «участник и группа из одной организации» на
        # уровне БД, а не сервисного слоя.
        sa.ForeignKeyConstraint(
            ['organization_id', 'user_group_id'],
            ['user_groups.organization_id', 'user_groups.id'],
            ondelete='CASCADE', onupdate='CASCADE',
            name='fk_user_group_members_group_org',
        ),
        sa.ForeignKeyConstraint(
            ['organization_id', 'user_id'],
            ['users.organization_id', 'users.id'],
            ondelete='CASCADE', onupdate='CASCADE',
            name='fk_user_group_members_user_org',
        ),
    )
    op.create_index('ix_user_group_members_user_id', 'user_group_members', ['user_id'])
    op.create_index('ix_user_group_members_organization_id', 'user_group_members', ['organization_id'])

    # ── группы сообществ (сообщество = publics) ──────────────────────────────
    op.create_table(
        'community_groups',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.UniqueConstraint('organization_id', 'name', name='uq_community_groups_org_name'),
        sa.UniqueConstraint('organization_id', 'id', name='uq_community_groups_org_id'),
    )
    op.create_index('ix_community_groups_organization_id', 'community_groups', ['organization_id'])

    op.create_table(
        'community_group_members',
        sa.Column('community_group_id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('public_id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(
            ['organization_id', 'community_group_id'],
            ['community_groups.organization_id', 'community_groups.id'],
            ondelete='CASCADE', onupdate='CASCADE',
            name='fk_community_group_members_group_org',
        ),
        sa.ForeignKeyConstraint(
            ['organization_id', 'public_id'],
            ['publics.organization_id', 'publics.id'],
            ondelete='CASCADE', onupdate='CASCADE',
            name='fk_community_group_members_public_org',
        ),
    )
    op.create_index('ix_community_group_members_public_id', 'community_group_members', ['public_id'])
    op.create_index(
        'ix_community_group_members_organization_id', 'community_group_members', ['organization_id']
    )

    # ── гранты ──────────────────────────────────────────────────────────────
    op.create_table(
        'access_grants',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('subject_type', subject_enum, nullable=False),
        sa.Column('subject_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('resource_type', resource_enum, nullable=False),
        sa.Column('resource_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('permission', permission_enum, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.UniqueConstraint(
            'subject_type', 'subject_id', 'resource_type', 'resource_id', 'permission',
            name='uq_access_grants_subject_resource_permission',
        ),
    )
    op.create_index('ix_access_grants_organization_id', 'access_grants', ['organization_id'])
    op.create_index('ix_access_grants_subject', 'access_grants', ['subject_type', 'subject_id'])
    op.create_index('ix_access_grants_resource', 'access_grants', ['resource_type', 'resource_id'])

    # ── аудит ───────────────────────────────────────────────────────────────
    op.create_table(
        'audit_log',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('actor_user_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('entity_type', sa.String(64), nullable=False),
        sa.Column('entity_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('action', sa.String(64), nullable=False),
        sa.Column('before_data', postgresql.JSONB(), nullable=True),
        sa.Column('after_data', postgresql.JSONB(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        # SET NULL: запись аудита обязана пережить удаление своего автора.
        sa.ForeignKeyConstraint(['actor_user_id'], ['users.id'], ondelete='SET NULL'),
    )
    op.create_index('ix_audit_log_org_created', 'audit_log', ['organization_id', 'created_at'])
    op.create_index('ix_audit_log_entity', 'audit_log', ['entity_type', 'entity_id'])


def downgrade() -> None:
    op.drop_table('audit_log')
    op.drop_table('access_grants')
    op.drop_table('community_group_members')
    op.drop_table('community_groups')
    op.drop_table('user_group_members')
    op.drop_table('user_groups')

    op.execute('DROP TYPE access_resource_type_enum')
    op.execute('DROP TYPE access_subject_type_enum')
    op.execute('DROP TYPE permission_enum')

    op.drop_constraint('uq_publics_org_id', 'publics', type_='unique')
    op.drop_constraint('uq_users_org_id', 'users', type_='unique')

    # Обратный маппинг. Различие editor/viewer восстановить неоткуда — оба
    # ушли в minion, назад все возвращаются как viewer.
    _swap_enum(
        table='users',
        column='status',
        old_type='user_status_enum',
        new_type='user_status_enum_old',
        new_values=('active', 'banned'),
        mapping={'active': 'active', 'blocked': 'banned', 'invited': 'active'},
        default='active',
    )
    _swap_enum(
        table='users',
        column='primary_role',
        old_type='user_role_enum',
        new_type='user_role_enum_old',
        new_values=('admin', 'editor', 'viewer', 'system_admin'),
        mapping={'superadmin': 'system_admin', 'admin': 'admin', 'minion': 'viewer'},
        default='viewer',
    )

    op.drop_constraint('ck_users_email_lowercase', 'users', type_='check')

    op.add_column('users', sa.Column('name', sa.String(255), nullable=True))
    op.execute("UPDATE users SET name = btrim(first_name || ' ' || last_name)")
    op.alter_column('users', 'name', nullable=False)
    op.drop_column('users', 'last_name')
    op.drop_column('users', 'first_name')
