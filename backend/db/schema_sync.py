from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from backend.db import Base


async def ensure_runtime_schema(engine: AsyncEngine) -> None:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

        comment_analysis_statements = (
            "ALTER TABLE comment_analysis ADD COLUMN IF NOT EXISTS author_type VARCHAR(64)",
            "ALTER TABLE comment_analysis ADD COLUMN IF NOT EXISTS message_type VARCHAR(64)",
            "ALTER TABLE comment_analysis ADD COLUMN IF NOT EXISTS is_official_response BOOLEAN NOT NULL DEFAULT false",
            "ALTER TABLE comment_analysis ADD COLUMN IF NOT EXISTS hierarchy JSON",
            "ALTER TABLE comment_analysis ADD COLUMN IF NOT EXISTS entities JSON",
            "ALTER TABLE comment_analysis ADD COLUMN IF NOT EXISTS classification_source VARCHAR(64)",
            "ALTER TABLE comment_analysis ADD COLUMN IF NOT EXISTS classification_state VARCHAR(32) NOT NULL DEFAULT 'done'",
            "ALTER TABLE comment_analysis ADD COLUMN IF NOT EXISTS candidates JSON",
            "ALTER TABLE comment_analysis ADD COLUMN IF NOT EXISTS needs_review BOOLEAN NOT NULL DEFAULT false",
            "ALTER TABLE comment_analysis ADD COLUMN IF NOT EXISTS classification_attempts INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE comment_analysis ADD COLUMN IF NOT EXISTS next_attempt_at TIMESTAMPTZ",
            "ALTER TABLE comment_analysis ALTER COLUMN analyzed_at DROP NOT NULL",
        )
        for statement in comment_analysis_statements:
            await connection.execute(text(statement))

        comment_analysis_index_statements = (
            "CREATE INDEX IF NOT EXISTS ix_comment_analysis_classification_source ON comment_analysis (classification_source)",
            "CREATE INDEX IF NOT EXISTS ix_comment_analysis_classification_state ON comment_analysis (classification_state)",
            "CREATE INDEX IF NOT EXISTS ix_comment_analysis_needs_review ON comment_analysis (needs_review)",
            "CREATE INDEX IF NOT EXISTS ix_comment_analysis_next_attempt_at ON comment_analysis (next_attempt_at) WHERE next_attempt_at IS NOT NULL",
            # Общий фильтр запросов аналитики; comment_id в конце — под join.
            "CREATE INDEX IF NOT EXISTS ix_comment_analysis_analytics_scope "
            "ON comment_analysis (classification_state, relevance, message_type, comment_id)",
        )
        for statement in comment_analysis_index_statements:
            await connection.execute(text(statement))

        # Те же запросы отбрасывают удалённые комментарии.
        await connection.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_comments_active_publication "
            "ON comments (publication_id) WHERE is_deleted = false"
        ))

        comment_analysis_backfill_statements = (
            """
            UPDATE comment_analysis
            SET classification_source = 'rule_based'
            WHERE classification_source IS NULL
              AND model_version LIKE 'vk_rule_based%'
            """,
            """
            UPDATE comment_analysis
            SET classification_source = 'llm'
            WHERE classification_source IS NULL
              AND model_version IS NOT NULL
              AND model_version NOT LIKE 'vk_rule_based%'
            """,
            """
            UPDATE comment_analysis
            SET classification_source = 'unknown'
            WHERE classification_source IS NULL
            """,
            # Упавшие до появления ретраев (attempts=0) получают право на повтор.
            # Новые терминальные failed имеют attempts>0 и сюда не попадают.
            """
            UPDATE comment_analysis
            SET next_attempt_at = now()
            WHERE classification_state = 'failed'
              AND next_attempt_at IS NULL
              AND classification_attempts = 0
            """,
        )
        for statement in comment_analysis_backfill_statements:
            await connection.execute(text(statement))

        for statement in (
            "ALTER TABLE organizations ADD COLUMN IF NOT EXISTS municipality_name VARCHAR(255)",
            "ALTER TABLE publics ADD COLUMN IF NOT EXISTS municipality_name VARCHAR(255)",
        ):
            await connection.execute(text(statement))

        for table in Base.metadata.sorted_tables:
            if "created_at" in table.c:
                await connection.execute(
                    text(
                        f'ALTER TABLE "{table.name}" '
                        'ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT now()'
                    )
                )
            if "updated_at" in table.c:
                await connection.execute(
                    text(
                        f'ALTER TABLE "{table.name}" '
                        'ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now()'
                    )
                )
