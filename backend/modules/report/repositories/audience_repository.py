"""Расчёт активности аудитории по комментариям VK.

Возвращает (рекомендованное окно публикации, heatmap 7×24). Заведомо
read-only: только SELECT'ы с группировкой по часу и дню недели.

Heatmap[dow][hour] = число комментариев, где dow по Postgres-конвенции
(0=вс, 6=сб). Окно — текстовая подсказка для редактора, собирается из
топ-часов и топ-дней через ``utils.audience.format_audience_window``.
"""
from __future__ import annotations

import uuid

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.comment_analysis import CommentAnalysis
from backend.db.comments import Comment
from backend.db.public_social_links import PublicSocialLink
from backend.db.publications import Publication
from backend.db.publics import Public
from backend.db.social_networks import SocialNetwork
from backend.modules.analytics.utils.municipality_filter import apply_comment_municipality_filter
from backend.modules.analytics.utils.public_link_filter import parse_public_social_link_ids
from backend.modules.report.utils.audience import format_audience_window
from backend.modules.report.utils.datetime_parse import period_to_since


class AudienceRepository:
    """SQL-подсчёт активности аудитории по комментариям VK."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def compute_activity(
        self,
        organization_id: uuid.UUID,
        public_social_link_id: str | None = None,
        period: str = "all",
        municipality_name: str | None = None,
        platform: str = "vk",
    ) -> tuple[str | None, list[list[int]] | None]:
        """Возвращает (recommended_post_window, heatmap_7x24)."""

        db = self._db
        since = period_to_since(period)

        base_filters = [
            Public.organization_id == organization_id,
            SocialNetwork.code == platform,
            Comment.is_deleted.is_(False),
        ]
        if since is not None:
            base_filters.append(func.coalesce(Comment.comment_date, Comment.created_at) >= since)
        link_ids = parse_public_social_link_ids(public_social_link_id)
        if link_ids:
            base_filters.append(Publication.public_social_link_id.in_(link_ids))

        def _joins(stmt):
            query = (
                stmt.select_from(Comment)
                .join(CommentAnalysis, CommentAnalysis.comment_id == Comment.id, isouter=True)
                .join(Publication, Publication.id == Comment.publication_id)
                .join(PublicSocialLink, PublicSocialLink.id == Publication.public_social_link_id)
                .join(SocialNetwork, SocialNetwork.id == PublicSocialLink.social_network_id)
                .join(Public, Public.id == PublicSocialLink.public_id)
                .where(and_(*base_filters))
            )
            return apply_comment_municipality_filter(query, municipality_name)

        # Одной группировки 7×24 хватает и для карты активности, и для
        # суммарных гистограмм часов/дней: не сканируем комментарии трижды.
        cell_q = _joins(select(
            func.extract("dow", func.coalesce(Comment.comment_date, Comment.created_at)).label("d"),
            func.extract("hour", func.coalesce(Comment.comment_date, Comment.created_at)).label("h"),
            func.count(Comment.id).label("n"),
        )).group_by("d", "h")
        heatmap: list[list[int]] = [[0] * 24 for _ in range(7)]
        has_data = False
        for d, h, n in (await db.execute(cell_q)).all():
            if d is None or h is None:
                continue
            di, hi = int(d), int(h)
            if 0 <= di < 7 and 0 <= hi < 24:
                heatmap[di][hi] = int(n)
                has_data = True

        hour_rows = [(h, sum(day[h] for day in heatmap)) for h in range(24)]
        dow_rows = [(d, sum(day)) for d, day in enumerate(heatmap)]
        hour_rows = sorted((item for item in hour_rows if item[1]), key=lambda item: (-item[1], item[0]))
        dow_rows = sorted((item for item in dow_rows if item[1]), key=lambda item: (-item[1], item[0]))
        window = format_audience_window(hour_rows, dow_rows)
        return window, (heatmap if has_data else None)
