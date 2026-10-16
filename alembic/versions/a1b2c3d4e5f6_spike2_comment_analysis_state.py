"""spike2: classification_state, candidates, needs_review on comment_analysis

Revision ID: a1b2c3d4e5f6
Revises: f3410cd5e9c7
Create Date: 2026-05-20

Контекст:
- Возвращаем колонку `classification_source` (была убрана командой при переезде, но
  она нужна для понимания, кто классифицировал запись: LLM, rule_based, fallback и т.п.).
- Добавляем колонку `classification_state` для очереди ingest-классификации:
  pending → processing → done | failed.
- Добавляем `candidates` (JSON) — top-N вариантов от LLM с confidence,
  для confidence-based routing и UI «второй вариант».
- Добавляем `needs_review` (bool) — ручной/автоматический ревью-флаг.

После этой миграции:
- Все существующие comment_analysis получают classification_state='done' (server_default).
- classification_source выставляется отдельным backfill-UPDATE по эвристике:
    model_version LIKE 'vk_rule_based%' -> 'rule_based'
    остальные с model_version NOT NULL  -> 'llm'
    с model_version NULL                -> 'unknown'
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "f3410cd5e9c7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    Идемпотентно: у части команды classification_source уже была добавлена
    вручную и заполнена своей логикой. Используем IF NOT EXISTS, чтобы
    миграция корректно отрабатывала и на «чистой» БД, и на той, где колонки
    уже частично есть. Backfill — только для строк с IS NULL.
    """
    # --- 1. Новые колонки (idempotent) ------------------------------------
    op.execute(
        "ALTER TABLE comment_analysis "
        "ADD COLUMN IF NOT EXISTS classification_source VARCHAR(64)"
    )
    op.execute(
        "ALTER TABLE comment_analysis "
        "ADD COLUMN IF NOT EXISTS classification_state VARCHAR(32) "
        "NOT NULL DEFAULT 'done'"
    )
    op.execute(
        "ALTER TABLE comment_analysis "
        "ADD COLUMN IF NOT EXISTS candidates JSON"
    )
    op.execute(
        "ALTER TABLE comment_analysis "
        "ADD COLUMN IF NOT EXISTS needs_review BOOLEAN NOT NULL DEFAULT false"
    )

    # --- 2. Индексы (idempotent) ------------------------------------------
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_comment_analysis_classification_source "
        "ON comment_analysis (classification_source)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_comment_analysis_classification_state "
        "ON comment_analysis (classification_state)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_comment_analysis_needs_review "
        "ON comment_analysis (needs_review)"
    )

    # --- 3. Backfill classification_source по эвристике -------------------
    # Только для строк, где значение ещё не проставлено вручную.
    op.execute(
        """
        UPDATE comment_analysis
        SET classification_source = 'rule_based'
        WHERE classification_source IS NULL
          AND model_version LIKE 'vk_rule_based%'
        """
    )
    op.execute(
        """
        UPDATE comment_analysis
        SET classification_source = 'llm'
        WHERE classification_source IS NULL
          AND model_version IS NOT NULL
          AND model_version NOT LIKE 'vk_rule_based%'
        """
    )
    op.execute(
        """
        UPDATE comment_analysis
        SET classification_source = 'unknown'
        WHERE classification_source IS NULL
        """
    )


def downgrade() -> None:
    """Downgrade schema. Идемпотентно через IF EXISTS."""
    op.execute("DROP INDEX IF EXISTS ix_comment_analysis_needs_review")
    op.execute("DROP INDEX IF EXISTS ix_comment_analysis_classification_state")
    op.execute("DROP INDEX IF EXISTS ix_comment_analysis_classification_source")
    op.execute("ALTER TABLE comment_analysis DROP COLUMN IF EXISTS needs_review")
    op.execute("ALTER TABLE comment_analysis DROP COLUMN IF EXISTS candidates")
    op.execute("ALTER TABLE comment_analysis DROP COLUMN IF EXISTS classification_state")
    op.execute("ALTER TABLE comment_analysis DROP COLUMN IF EXISTS classification_source")
