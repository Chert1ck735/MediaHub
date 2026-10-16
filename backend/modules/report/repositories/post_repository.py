"""SQL-доступ к опубликованным VK-постам для генерации отчёта.

Сложный JOIN, у которого две основные задачи:
  * вытащить пост вместе со ссылкой на его публикацию и площадку;
  * подцепить последнюю метрику поста и последнюю метрику паблика
    (через correlated subquery на ``func.max(metric_date)``).

Результат — список плоских словарей в формате, который ожидают
``analyzers/vk_analyzer.py`` и ``charts/vk_charts.py``.
"""
from __future__ import annotations

import uuid

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.post_metrics import PostMetric
from backend.db.posts import Post
from backend.db.public_metrics import PublicMetric
from backend.db.public_social_links import PublicSocialLink
from backend.db.publications import Publication
from backend.db.publics import Public
from backend.db.social_networks import SocialNetwork
from backend.modules.analytics.utils.municipality_filter import apply_public_municipality_filter
from backend.modules.analytics.utils.public_link_filter import parse_public_social_link_ids
from backend.modules.report.utils.datetime_parse import period_cutoff


class ReportPostRepository:
    """Чтение VK-постов с привязкой к метрикам."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def load_vk_posts(
        self,
        organization_id: uuid.UUID,
        public_social_link_id: str | None = None,
        period: str = "all",
        municipality_name: str | None = None,
        platform: str = "vk",
    ) -> list[dict]:
        """Возвращает посты организации с последними метриками за период."""

        cutoff = period_cutoff(period)
        latest_post_metric = (
            select(
                PostMetric.publication_id.label("publication_id"),
                func.max(PostMetric.metric_date).label("metric_date"),
            )
            .group_by(PostMetric.publication_id)
            .subquery()
        )
        latest_public_metric = (
            select(
                PublicMetric.public_social_link_id.label("public_social_link_id"),
                func.max(PublicMetric.metric_date).label("metric_date"),
            )
            .group_by(PublicMetric.public_social_link_id)
            .subquery()
        )

        stmt = (
            select(
                Post.id,
                Post.created_at,
                Post.published_at,
                Publication.published_at.label("publication_published_at"),
                Post.title,
                Post.text_draft,
                Post.text_generated,
                Post.text_final,
                PostMetric.views,
                PostMetric.likes,
                PostMetric.comments_count,
                PostMetric.reposts,
                PublicMetric.subscribers_count,
                PublicSocialLink.id.label("source_key"),
                Public.name.label("channel"),
                PublicSocialLink.url.label("source_url"),
                Publication.url.label("post_url"),
            )
            .join(Publication, Publication.post_id == Post.id)
            .join(
                PublicSocialLink,
                PublicSocialLink.id == Publication.public_social_link_id,
            )
            .join(Public, Public.id == PublicSocialLink.public_id)
            .join(SocialNetwork, SocialNetwork.id == PublicSocialLink.social_network_id)
            .where(SocialNetwork.code == platform)
            .join(
                latest_post_metric,
                latest_post_metric.c.publication_id == Publication.id,
                isouter=True,
            )
            .join(
                PostMetric,
                and_(
                    PostMetric.publication_id == Publication.id,
                    PostMetric.metric_date == latest_post_metric.c.metric_date,
                ),
                isouter=True,
            )
            .join(
                latest_public_metric,
                latest_public_metric.c.public_social_link_id == Publication.public_social_link_id,
                isouter=True,
            )
            .join(
                PublicMetric,
                and_(
                    PublicMetric.public_social_link_id == Publication.public_social_link_id,
                    PublicMetric.metric_date == latest_public_metric.c.metric_date,
                ),
                isouter=True,
            )
            .where(Public.organization_id == organization_id)
            .order_by(Post.published_at.asc().nulls_last(), Post.created_at.asc())
        )
        link_ids = parse_public_social_link_ids(public_social_link_id)
        if link_ids:
            stmt = stmt.where(PublicSocialLink.id.in_(link_ids))
        stmt = apply_public_municipality_filter(stmt, municipality_name)
        if cutoff is not None:
            stmt = stmt.where(
                func.coalesce(
                    Publication.published_at,
                    Post.published_at,
                    Post.created_at,
                ) >= cutoff
            )
        result = await self._db.execute(stmt)
        posts: list[dict] = []
        for row in result.all():
            dt = row.publication_published_at or row.published_at or row.created_at
            posts.append(
                {
                    "id": str(row.id),
                    "date": dt.isoformat(sep=" ", timespec="seconds") if dt else "",
                    "text": (
                        row.text_final
                        or row.text_generated
                        or row.text_draft
                        or row.title
                        or ""
                    ).strip(),
                    "likes": int(row.likes or 0),
                    "reposts": int(row.reposts or 0),
                    "comments": int(row.comments_count or 0),
                    "views": int(row.views or 0),
                    "group_members": int(row.subscribers_count or 0),
                    "source_key": str(row.source_key),
                    "channel": row.channel,
                    "source_url": row.source_url,
                    "url": row.post_url or None,
                }
            )
        return posts
