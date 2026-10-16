"""Обращения по дням в разрезе площадок.

Нужны, чтобы искать всплески (`tools/find_spikes.py`) не имея прямого доступа
к базе: агрегаты по периодам такого не дают, а поштучные даты — дают.

Отдаются только счётчики: ни текстов, ни авторов.
"""
from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.users import User
from backend.modules.analytics.constants import APPEAL_MESSAGE_TYPES
from backend.modules.organization.guards import accessible_community_ids

# Канон обращения тот же, что в appeal_scope: релевантный комментарий с типом
# жалобы/просьбы, доведённый до конца классификации и не являющийся ответом
# сообщества (у сообществ VK отрицательный идентификатор).
SQL = """
    SELECT date_trunc('day', COALESCE(c.comment_date, c.created_at))::date AS day,
           p.id   AS public_id,
           p.name AS public,
           count(*) AS appeals
    FROM comments c
    JOIN comment_analysis ca ON ca.comment_id = c.id
    JOIN publications pub ON pub.id = c.publication_id
    JOIN public_social_links psl ON psl.id = pub.public_social_link_id
    JOIN publics p ON p.id = psl.public_id
    WHERE c.is_deleted = false
      AND ca.classification_state = 'done'
      AND ca.relevance = 'relevant'
      AND ca.message_type = ANY(:types)
      AND COALESCE(ca.is_official_response, false) = false
      AND (c.author_external_id IS NULL OR c.author_external_id NOT LIKE '-%')
      AND p.organization_id = :org_id
      AND COALESCE(c.comment_date, c.created_at) >= :since
      AND (:all_publics OR p.id = ANY(:allowed))
    GROUP BY day, p.id, p.name
    ORDER BY day
"""


class AppealDailyService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def daily_counts(self, actor: User, since: date) -> list[dict]:
        allowed = await accessible_community_ids(self._db, actor)
        if allowed is not None and not allowed:
            return []

        rows = (await self._db.execute(text(SQL), {
            "types": list(APPEAL_MESSAGE_TYPES),
            "org_id": actor.organization_id,
            "since": since,
            "all_publics": allowed is None,
            "allowed": [uuid.UUID(str(pid)) for pid in (allowed or [])],
        })).mappings().all()

        return [
            {
                "day": row["day"].isoformat(),
                "public_id": str(row["public_id"]),
                "public": row["public"],
                "appeals": row["appeals"],
            }
            for row in rows
        ]
