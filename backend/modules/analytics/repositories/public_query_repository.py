"""Query-репозиторий для analytics publics/publications/comments."""

import uuid
from typing import Any

from sqlalchemy import select, desc, func
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db import Publication, User, Post, PostMetric, Public, PublicSocialLink, Comment, PublicMetric, Region
from backend.db.social_networks import SocialNetwork
from backend.modules.vk.utils.constants import AUTO_DEFAULT_PUBLIC_DESCRIPTION


class PublicQueryRepository:
    """SQL-доступ для публичных analytics-страниц."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def list_publics(self, user: User) -> list[dict[str, Any]]:
        """Возвращает импортированные площадки с агрегатами по ссылкам."""

        rows = await self._db.execute(
            select(
                Public.id,
                Public.name,
                Public.description,
                Public.region_id,
                Public.municipality_name,
                Region.name.label("region_name"),
                PublicSocialLink.id.label("link_id"),
                PublicSocialLink.url,
                PublicSocialLink.external_public_id,
                PublicSocialLink.title,
                PublicSocialLink.autoparse_enabled,
                PublicSocialLink.last_autoparse_at,
                PublicSocialLink.last_autoparse_error,
                SocialNetwork.code.label("social_network_code"),
                SocialNetwork.name.label("social_network_name"),
            )
            .join(Region, Region.id == Public.region_id, isouter=True)
            .join(PublicSocialLink, PublicSocialLink.public_id == Public.id, isouter=True)
            .join(SocialNetwork, SocialNetwork.id == PublicSocialLink.social_network_id, isouter=True)
            .where(Public.organization_id == user.organization_id)
            .where(Public.description.is_distinct_from(AUTO_DEFAULT_PUBLIC_DESCRIPTION))
            .order_by(Public.created_at.desc())
        )

        items: dict[str, dict[str, Any]] = {}
        for row in rows.all():
            public_id = str(row.id)
            bucket = items.setdefault(
                public_id,
                {
                    "id": public_id,
                    "name": row.name,
                    "description": row.description,
                    "region_id": str(row.region_id) if row.region_id else None,
                    "region_name": row.region_name,
                    "municipality_name": row.municipality_name,
                    "links": [],
                },
            )
            if row.link_id:
                bucket["links"].append(
                    {
                        "id": str(row.link_id),
                        "url": row.url,
                        "external_public_id": row.external_public_id,
                        "title": row.title,
                        "autoparse_enabled": bool(row.autoparse_enabled),
                        "last_autoparse_at": (
                            row.last_autoparse_at.isoformat()
                            if row.last_autoparse_at
                            else None
                        ),
                        "last_autoparse_error": row.last_autoparse_error,
                        "social_network_code": row.social_network_code,
                        "social_network_name": row.social_network_name,
                    }
                )

        links = [link for bucket in items.values() for link in bucket["links"]]
        await self._fill_metrics_for_links(links)

        return list(items.values())

    async def list_publications(
        self,
        user: User,
        *,
        public_social_link_id: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Возвращает публикации организации с метриками."""

        stmt = (
            select(
                Publication.id,
                Publication.url,
                Publication.published_at,
                Publication.external_post_id,
                Post.title,
                Post.text_final,
                Post.public_id,
                PostMetric.views,
                PostMetric.likes,
                PostMetric.comments_count,
                PostMetric.reposts,
            )
            .join(Post, Post.id == Publication.post_id)
            .join(PostMetric, PostMetric.publication_id == Publication.id, isouter=True)
            .join(PublicSocialLink, PublicSocialLink.id == Publication.public_social_link_id)
            .join(Public, Public.id == PublicSocialLink.public_id)
            .where(Public.organization_id == user.organization_id)
            .order_by(desc(Publication.published_at))
            .limit(min(max(limit, 1), 200))
        )

        if public_social_link_id:
            stmt = stmt.where(Publication.public_social_link_id == public_social_link_id)

        rows = await self._db.execute(stmt)
        return [
            {
                "publication_id": str(row.id),
                "url": row.url,
                "external_post_id": row.external_post_id,
                "published_at": row.published_at.isoformat() if row.published_at else None,
                "title": row.title,
                "text": row.text_final,
                "public_id": str(row.public_id) if row.public_id else None,
                "views": int(row.views or 0),
                "likes": int(row.likes or 0),
                "comments_count": int(row.comments_count or 0),
                "reposts": int(row.reposts or 0),
            }
            for row in rows.all()
        ]

    async def list_recent_comments(
        self,
        user: User,
        *,
        publication_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Возвращает последние комментарии организации."""

        stmt = (
            select(
                Comment.id,
                Comment.publication_id,
                Comment.text,
                Comment.author_name,
                Comment.author_external_id,
                Comment.comment_date,
                Comment.external_id,
            )
            .join(Publication, Publication.id == Comment.publication_id)
            .join(PublicSocialLink, PublicSocialLink.id == Publication.public_social_link_id)
            .join(Public, Public.id == PublicSocialLink.public_id)
            .where(Public.organization_id == user.organization_id)
            .where(Comment.is_deleted.is_(False))
            .order_by(desc(Comment.comment_date))
            .limit(min(max(limit, 1), 500))
        )

        if publication_id:
            stmt = stmt.where(Comment.publication_id == publication_id)

        rows = await self._db.execute(stmt)
        return [
            {
                "id": str(row.id),
                "publication_id": str(row.publication_id) if row.publication_id else None,
                "text": row.text,
                "author_name": row.author_name,
                "author_external_id": row.author_external_id,
                "comment_date": row.comment_date.isoformat() if row.comment_date else None,
                "external_id": row.external_id,
            }
            for row in rows.all()
        ]

    async def _fill_metrics_for_links(self, links: list[dict[str, Any]]) -> None:
        """Дополняет все ссылки агрегатами за четыре запроса.

        Раньше на каждую ссылку уходило четыре отдельных запроса: при трёх
        сотнях площадок это больше тысячи обращений к базе подряд, и ответ
        занимал под сорок секунд.
        """

        if not links:
            return

        link_ids = [uuid.UUID(link["id"]) for link in links]
        by_id = {link["id"]: link for link in links}

        for link in links:
            link["publications_count"] = 0
            link["total_views"] = 0
            link["total_likes"] = 0
            link["total_reposts"] = 0
            link["total_comments"] = 0
            link["first_comment_at"] = None
            link["last_comment_at"] = None

        publication_rows = await self._db.execute(
            select(
                Publication.public_social_link_id,
                func.count(func.distinct(Publication.id)).label("publications"),
                func.coalesce(func.sum(PostMetric.views), 0).label("views"),
                func.coalesce(func.sum(PostMetric.likes), 0).label("likes"),
                func.coalesce(func.sum(PostMetric.reposts), 0).label("reposts"),
            )
            .select_from(Publication)
            .join(PostMetric, PostMetric.publication_id == Publication.id, isouter=True)
            .where(Publication.public_social_link_id.in_(link_ids))
            .group_by(Publication.public_social_link_id)
        )
        for row in publication_rows.all():
            link = by_id.get(str(row.public_social_link_id))
            if link is None:
                continue
            link["publications_count"] = int(row.publications or 0)
            link["total_views"] = int(row.views or 0)
            link["total_likes"] = int(row.likes or 0)
            link["total_reposts"] = int(row.reposts or 0)

        at = func.coalesce(Comment.comment_date, Comment.created_at)
        comment_rows = await self._db.execute(
            select(
                Publication.public_social_link_id,
                func.count(Comment.id).label("comments"),
                func.min(at).label("first_at"),
                func.max(at).label("last_at"),
            )
            .select_from(Comment)
            .join(Publication, Publication.id == Comment.publication_id)
            .where(Publication.public_social_link_id.in_(link_ids))
            .where(Comment.is_deleted.is_(False))
            .group_by(Publication.public_social_link_id)
        )
        for row in comment_rows.all():
            link = by_id.get(str(row.public_social_link_id))
            if link is None:
                continue
            link["total_comments"] = int(row.comments or 0)
            link["first_comment_at"] = row.first_at.isoformat() if row.first_at else None
            link["last_comment_at"] = row.last_at.isoformat() if row.last_at else None

        # Последняя запись подписчиков по каждой ссылке: DISTINCT ON берёт
        # первую строку каждой группы в заданном порядке.
        metric_rows = await self._db.execute(
            select(PublicMetric.public_social_link_id, PublicMetric.subscribers_count)
            .where(PublicMetric.public_social_link_id.in_(link_ids))
            .distinct(PublicMetric.public_social_link_id)
            .order_by(
                PublicMetric.public_social_link_id,
                desc(PublicMetric.metric_date),
            )
        )
        for link_id, subscribers in metric_rows.all():
            link = by_id.get(str(link_id))
            if link is not None and subscribers is not None:
                link["subscribers_count"] = subscribers

