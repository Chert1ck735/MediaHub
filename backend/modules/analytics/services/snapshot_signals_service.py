"""Агрегаты по комментариям для эндпоинта Summary.

Сервис чистого чтения: считает по БД всё, что отображается на
панелях ``/summary`` и в Динамике площадки.

Поддерживает:
  * фильтр периода через ``since``;
  * фильтр одной VK-площадки через ``link_id``;
  * исключение ответов самого сообщества ``author_external_id LIKE '-%'``.

SQL-выборки делегированы в ``SignalsRepository``; здесь остаётся только
пост-обработка: сборка breakdown'ов и рекомендованного окна постинга.
"""
from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.users import User
from backend.modules.analytics.mappers.case_mapper import (
    to_message_type_breakdown,
    to_sentiment_breakdown,
)
from backend.modules.analytics.constants import COMPLAINT_MESSAGE_TYPES
from backend.modules.analytics.repositories.signals_repository import SignalsRepository
from backend.modules.analytics.schemas import CategoryCountItem, RelevanceBreakdown
from backend.modules.analytics.utils.signal_counts import (
    empty_message_type_counts,
    empty_sentiment_counts,
)
from backend.modules.analytics.utils.public_link_filter import PublicSocialLinkFilter
from backend.modules.analytics.utils.time_helpers import format_post_window


class SnapshotSignalsService:
    """Подсчитывает агрегаты по комментариям VK для summary-эндпоинта."""

    def __init__(
        self,
        db: AsyncSession,
        *,
        signals_repository: SignalsRepository | None = None,
    ) -> None:
        """Сохраняет асинхронную сессию БД."""
        self._db = db
        self._repo = signals_repository or SignalsRepository(db)

    async def get_counts(
        self,
        snapshot_id: str,
        user: User,
        *,
        since: datetime | None = None,
        link_id: PublicSocialLinkFilter = None,
        municipality_name: str | None = None,
    ) -> dict[str, Any]:
        """Возвращает агрегаты snapshot'а с фильтрами периода и площадки."""

        snapshot_uuid = uuid.UUID(snapshot_id)
        repo = self._repo

        total_comments = await repo.count_total_comments(
            user,
            since=since,
            link_id=link_id,
            municipality_name=municipality_name,
        )
        classified_comments = await repo.count_classified_comments(
            user,
            since=since,
            link_id=link_id,
            municipality_name=municipality_name,
        )
        relevant_comments = await repo.count_relevant_comments(
            snapshot_uuid,
            since=since,
            link_id=link_id,
            municipality_name=municipality_name,
        )

        complaints = await repo.count_relevant_by_message_types(
            user,
            message_types=list(COMPLAINT_MESSAGE_TYPES),
            since=since,
            link_id=link_id,
            municipality_name=municipality_name,
        )
        requests = await repo.count_relevant_by_message_types(
            user,
            message_types=["request"],
            since=since,
            link_id=link_id,
            municipality_name=municipality_name,
        )
        appeals = await repo.count_appeals(
            user,
            since=since,
            link_id=link_id,
            municipality_name=municipality_name,
        )
        gratitude = await repo.count_gratitude(
            user,
            since=since,
            link_id=link_id,
            municipality_name=municipality_name,
        )
        # остаток, а не отдельный запрос: три полосы всегда дают классифицированные
        other = max(classified_comments - appeals - gratitude, 0)
        filtered = max(total_comments - relevant_comments, 0)

        sentiment_counts = empty_sentiment_counts()
        for sentiment, count in await repo.sentiment_rows(
            user,
            since=since,
            link_id=link_id,
            municipality_name=municipality_name,
        ):
            if sentiment:
                sentiment_counts[sentiment.value] = int(count or 0)

        message_type_counts = empty_message_type_counts()
        for message_type, count in await repo.message_type_rows(
            user,
            since=since,
            link_id=link_id,
            municipality_name=municipality_name,
        ):
            key = str(message_type or "").strip()
            if key in message_type_counts:
                message_type_counts[key] = int(count or 0)

        category_sentiment_map: dict[str, dict[str, int]] = defaultdict(
            lambda: {"positive": 0, "neutral": 0, "negative": 0}
        )
        for category, sentiment, count in await repo.category_sentiment_rows(
            user,
            since=since,
            link_id=link_id,
            municipality_name=municipality_name,
        ):
            label = str(category or "").strip() or "Без категории"
            if sentiment:
                category_sentiment_map[label][sentiment.value] = int(count or 0)

        category_counts: dict[str, int] = defaultdict(int)
        for category, count in await repo.category_rows(
            user,
            since=since,
            link_id=link_id,
            municipality_name=municipality_name,
        ):
            label = str(category or "").strip() or "Без категории"
            category_counts[label] += int(count or 0)

        category_breakdown: list[CategoryCountItem] = []
        for category, count in sorted(
            category_counts.items(),
            key=lambda item: item[1],
            reverse=True,
        ):
            if count <= 0 or category == "Без категории":
                continue
            sentiments = category_sentiment_map.get(category, {})
            category_breakdown.append(
                CategoryCountItem(
                    category=category,
                    count=count,
                    negative_count=int(sentiments.get("negative", 0)),
                    neutral_count=int(sentiments.get("neutral", 0)),
                    positive_count=int(sentiments.get("positive", 0)),
                )
            )

        unclassified_count = int(category_counts.get("Без категории", 0))

        hour_rows = [
            (int(hour), int(count))
            for hour, count in await repo.hour_rows(
                user,
                since=since,
                link_id=link_id,
                municipality_name=municipality_name,
            )
            if hour is not None
        ]
        dow_rows = [
            (int(day), int(count))
            for day, count in await repo.dow_rows(
                user,
                since=since,
                link_id=link_id,
                municipality_name=municipality_name,
            )
            if day is not None
        ]
        recommended_window = format_post_window(hour_rows, dow_rows)

        return {
            "total_comments": total_comments,
            "classified_comments": classified_comments,
            "relevant_comments": relevant_comments,
            "unclassified_count": unclassified_count,
            "recommended_post_window": recommended_window,
            "complaints": complaints,
            "requests": requests,
            "appeals": appeals,
            "gratitude": gratitude,
            "other": other,
            "filtered": filtered,
            "sentiment_breakdown": to_sentiment_breakdown(sentiment_counts).model_dump(),
            "message_type_breakdown": to_message_type_breakdown(message_type_counts).model_dump(),
            "relevance_breakdown": RelevanceBreakdown(
                relevant=relevant_comments,
                irrelevant=filtered,
            ).model_dump(),
            "category_breakdown": [
                item.model_dump()
                for item in category_breakdown[:8]
            ],
        }
