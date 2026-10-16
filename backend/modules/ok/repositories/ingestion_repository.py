"""Репозиторий OK-импорта: только SQL и сохранение данных."""

import uuid
from datetime import date, datetime, timezone
from typing import Any, Iterable

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db import (
    Comment,
    ContentTypeEnum,
    MediaItem,
    MetricPeriodEnum,
    Organization,
    Post,
    PostMetric,
    PostOriginEnum,
    Public,
    PublicMetric,
    PublicSocialLink,
    Publication,
    PublicationStatusEnum,
    SocialNetwork,
    User,
)
from backend.db.comment_analysis import CommentAnalysis
from backend.modules.audit_utils import add_action_log
from backend.modules.comment_deduplication import load_comment_dedup_state
from backend.modules.metadata_utils import get_or_create_data_source, sync_post_tags
from backend.modules.ok.dto.dto import OkTopicStatsDTO
from backend.modules.ok.dto.topic_mapper import OkTopicMapper
from backend.modules.ok.utils.errors import OkIngestionError


class OkIngestionRepository:
    """Сохраняет OK-импорт в БД без вызовов OK API и HTTP-логики."""

    def __init__(self, db: AsyncSession, mapper: OkTopicMapper | None = None) -> None:
        self.db = db
        self.mapper = mapper or OkTopicMapper()

    async def get_or_create_ok_network(self) -> SocialNetwork:
        """Возвращает или создает SocialNetwork(code='ok')."""

        result = await self.db.execute(select(SocialNetwork).where(SocialNetwork.code == "ok"))
        network = result.scalar_one_or_none()
        if network is not None:
            return network
        network = SocialNetwork(code="ok", name="OK", description="Одноклассники")
        self.db.add(network)
        await self.db.flush()
        return network

    async def resolve_organization(self, user: User) -> Organization:
        """Возвращает организацию пользователя или выбрасывает ошибку."""

        if user.organization_id:
            result = await self.db.execute(
                select(Organization).where(Organization.id == user.organization_id)
            )
            organization = result.scalar_one_or_none()
            if organization is not None:
                return organization
        raise OkIngestionError(
            "У текущего пользователя не задана организация. Сначала зарегистрируйтесь."
        )

    async def get_or_create_public(
        self, org: Organization, name: str, description: str | None
    ) -> Public:
        """Возвращает или создает Public."""

        result = await self.db.execute(
            select(Public).where(Public.organization_id == org.id, Public.name == name)
        )
        public = result.scalar_one_or_none()
        if public is not None:
            return public
        public = Public(
            organization_id=org.id, name=name, description=description, is_active=True
        )
        self.db.add(public)
        await self.db.flush()
        return public

    async def get_or_create_social_link(
        self,
        public: Public,
        network: SocialNetwork,
        *,
        url: str,
        external_public_id: str,
        title: str | None,
    ) -> PublicSocialLink:
        """Возвращает или создает PublicSocialLink."""

        result = await self.db.execute(
            select(PublicSocialLink).where(
                PublicSocialLink.public_id == public.id,
                PublicSocialLink.social_network_id == network.id,
                PublicSocialLink.external_public_id == external_public_id,
            )
        )
        link = result.scalar_one_or_none()
        if link is not None:
            link.url = url
            link.title = title or link.title
            link.is_active = True
            return link
        link = PublicSocialLink(
            public_id=public.id,
            social_network_id=network.id,
            title=title,
            url=url,
            external_public_id=external_public_id,
            is_primary=True,
            is_active=True,
        )
        self.db.add(link)
        await self.db.flush()
        return link

    async def upsert_topic_with_publication(
        self,
        *,
        org: Organization,
        public: Public,
        link: PublicSocialLink,
        user: User,
        group_id: str,
        topic: dict[str, Any],
    ) -> tuple[Post, Publication]:
        """Создает или обновляет Post и Publication для темы OK."""

        source = await self._get_or_create_ok_source()
        external_id = self.mapper.external_post_id(group_id, topic)
        url = self.mapper.post_url(group_id, topic)
        text = self.mapper.extract_text(topic)
        title = (text.split("\n", 1)[0] if text else "(без текста)")[:255] or "(без текста)"
        published_at = self.mapper.published_at(topic)
        content_type = self.mapper.detect_content_type(topic)

        result = await self.db.execute(
            select(Publication).where(
                Publication.public_social_link_id == link.id,
                Publication.external_post_id == external_id,
            )
        )
        publication = result.scalar_one_or_none()
        if publication is not None:
            post = await self._require_post(publication.post_id)
            self._update_post(post, public, source.id, text, published_at, content_type)
            self._update_publication(publication, url, published_at, content_type)
            await self.sync_ok_topic_metadata(post, topic)
            return post, publication

        post = Post(
            organization_id=org.id,
            public_id=public.id,
            author_id=user.id,
            title=title,
            text_draft=None,
            text_generated=None,
            text_final=text,
            summary=(text[:500] or None),
            origin=PostOriginEnum.parsed,
            content_type=content_type,
            status=PublicationStatusEnum.published,
            published_at=published_at,
            source_id=source.id,
        )
        self.db.add(post)
        await self.db.flush()
        await self.sync_ok_topic_metadata(post, topic)

        publication = Publication(
            post_id=post.id,
            public_social_link_id=link.id,
            external_post_id=external_id,
            url=url,
            status=PublicationStatusEnum.published,
            content_type=content_type,
            published_at=published_at,
            last_synced_at=datetime.now(timezone.utc),
        )
        self.db.add(publication)
        await self.db.flush()
        return post, publication

    async def upsert_post_metric(
        self, publication: Publication, topic: dict[str, Any], stats: OkTopicStatsDTO
    ) -> None:
        """Создает или обновляет дневную метрику темы."""

        metric_date: date = self.mapper.published_at(topic).date()
        result = await self.db.execute(
            select(PostMetric).where(
                PostMetric.publication_id == publication.id,
                PostMetric.metric_date == metric_date,
            )
        )
        metric = result.scalar_one_or_none()
        if metric is None:
            self.db.add(
                PostMetric(
                    publication_id=publication.id,
                    metric_date=metric_date,
                    collected_at=datetime.now(timezone.utc),
                    views=stats.views,
                    likes=stats.likes,
                    comments_count=stats.comments,
                    reposts=stats.reshares,
                )
            )
            return
        metric.views = stats.views
        metric.likes = stats.likes
        metric.comments_count = stats.comments
        metric.reposts = stats.reshares

    async def upsert_comments(
        self, publication: Publication, ok_comments: Iterable[dict[str, Any]]
    ) -> int:
        """Сохраняет комментарии и ставит новые в очередь LLM-классификации."""

        saved = 0
        dedup = await load_comment_dedup_state(self.db, publication.id)
        parent_map: dict[str, uuid.UUID] = dict(dedup.by_external_id)
        for raw in ok_comments:
            external_id = str(raw.get("id") or "")
            if not external_id:
                continue

            text = self.mapper.comment_text(raw)
            if not text:
                continue
            author_external_id = self.mapper.comment_author_id(raw)
            duplicate_id = dedup.duplicate_id(
                external_id=external_id,
                author_external_id=author_external_id,
                text=text,
            )
            if duplicate_id is not None:
                parent_map[external_id] = duplicate_id
                dedup.by_external_id[external_id] = duplicate_id
                continue

            parent_external = self.mapper.comment_parent_id(raw)
            parent_id = parent_map.get(parent_external) if parent_external else None

            comment = Comment(
                publication_id=publication.id,
                parent_comment_id=parent_id,
                external_id=external_id,
                text=text,
                author_external_id=author_external_id,
                comment_date=self.mapper.comment_date(raw),
                parsed_at=datetime.now(timezone.utc),
                is_deleted=False,
            )
            self.db.add(comment)
            await self.db.flush()
            self.db.add(CommentAnalysis(comment_id=comment.id, classification_state="pending"))
            parent_map[external_id] = comment.id
            dedup.remember(
                comment_id=comment.id,
                external_id=external_id,
                author_external_id=author_external_id,
                text=text,
            )
            saved += 1
        return saved

    async def upsert_public_metric(
        self,
        link: PublicSocialLink,
        *,
        members: int,
        posts_total: int,
        sum_views: int,
        sum_likes: int,
        sum_comments: int,
        sum_reposts: int,
    ) -> None:
        """Создает или обновляет дневную метрику паблика."""

        today = datetime.now(timezone.utc).date()
        result = await self.db.execute(
            select(PublicMetric).where(
                PublicMetric.public_social_link_id == link.id,
                PublicMetric.period == MetricPeriodEnum.day,
                PublicMetric.metric_date == today,
            )
        )
        metric = result.scalar_one_or_none()
        avg_views = (sum_views / posts_total) if posts_total else 0.0
        avg_engagement = (
            ((sum_likes + sum_comments + sum_reposts) / sum_views * 100.0) if sum_views else 0.0
        )
        organic_reach = (sum_views / members * 100.0) if members else 0.0
        if metric is None:
            self.db.add(
                PublicMetric(
                    public_social_link_id=link.id,
                    period=MetricPeriodEnum.day,
                    metric_date=today,
                    subscribers_count=members,
                    total_posts=posts_total,
                    total_views=sum_views,
                    total_likes=sum_likes,
                    total_comments=sum_comments,
                    total_reposts=sum_reposts,
                    avg_views=avg_views,
                    avg_engagement=avg_engagement,
                    organic_reach=organic_reach,
                    posting_regularity=float(posts_total),
                    calculated_at=datetime.now(timezone.utc),
                )
            )
            return
        metric.subscribers_count = members
        metric.total_posts = posts_total
        metric.total_views = sum_views
        metric.total_likes = sum_likes
        metric.total_comments = sum_comments
        metric.total_reposts = sum_reposts
        metric.avg_views = avg_views
        metric.avg_engagement = avg_engagement
        metric.organic_reach = organic_reach
        metric.posting_regularity = float(posts_total)

    async def sync_ok_topic_metadata(self, post: Post, topic: dict[str, Any]) -> None:
        """Синхронизирует медиа и теги поста."""

        await self._sync_post_media(post, topic)
        await sync_post_tags(self.db, post, self.mapper.metadata_tags(topic))

    async def add_ingest_audit_log(
        self,
        *,
        user: User,
        link: PublicSocialLink,
        public: Public,
        mode: str,
        posts_imported: int,
        comments_imported: int,
    ) -> None:
        """Пишет audit-log успешного OK-импорта."""

        add_action_log(
            self.db,
            user_id=user.id,
            action="ok_ingest_completed",
            entity_type="public_social_link",
            entity_id=link.id,
            details={
                "mode": mode,
                "public_id": public.id,
                "posts_imported": posts_imported,
                "comments_imported": comments_imported,
            },
        )

    async def commit(self) -> None:
        """Фиксирует транзакцию."""

        await self.db.commit()

    async def rollback(self) -> None:
        """Откатывает транзакцию."""

        await self.db.rollback()

    async def _get_or_create_ok_source(self):
        """Возвращает источник данных ok_api."""

        return await get_or_create_data_source(
            self.db,
            source_type="api",
            name="ok_api",
            description="Импорт тем и комментариев через OK API",
            configuration={"platform": "ok"},
        )

    async def _sync_post_media(self, post: Post, topic: dict[str, Any]) -> None:
        """Перезаписывает медиа-вложения поста."""

        await self.db.execute(delete(MediaItem).where(MediaItem.post_id == post.id))
        for item in self.mapper.extract_media_entries(topic):
            self.db.add(
                MediaItem(
                    post_id=post.id,
                    url=item["url"],
                    type=item["type"],
                    external_id=item["external_id"] or None,
                    sort_order=item["sort_order"],
                )
            )

    async def _require_post(self, post_id) -> Post:
        """Возвращает Post по id."""

        result = await self.db.execute(select(Post).where(Post.id == post_id))
        return result.scalar_one()

    def _update_post(
        self,
        post: Post,
        public: Public,
        source_id,
        text: str,
        published_at: datetime,
        content_type: ContentTypeEnum,
    ) -> None:
        """Обновляет Post."""

        post.text_final = text
        post.public_id = public.id
        post.summary = text[:500] or None
        post.published_at = published_at
        post.origin = PostOriginEnum.parsed
        post.content_type = content_type
        post.source_id = source_id

    def _update_publication(
        self,
        publication: Publication,
        url: str,
        published_at: datetime,
        content_type: ContentTypeEnum,
    ) -> None:
        """Обновляет Publication."""

        publication.url = url
        publication.published_at = published_at
        publication.last_synced_at = datetime.now(timezone.utc)
        publication.content_type = content_type
        publication.status = PublicationStatusEnum.published
