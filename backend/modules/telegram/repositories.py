"""SQL-слой импорта Telegram без MTProto-вызовов."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db import (
    Comment,
    ContentTypeEnum,
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
from backend.modules.telegram.client import (
    TelegramChannelDTO,
    TelegramCommentDTO,
    TelegramMessageDTO,
)
from backend.modules.telegram.errors import TelegramIngestionError


class TelegramIngestionRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def resolve_organization(self, user: User) -> Organization:
        if user.organization_id:
            result = await self.db.execute(select(Organization).where(Organization.id == user.organization_id))
            org = result.scalar_one_or_none()
            if org is not None:
                return org
        raise TelegramIngestionError("У текущего пользователя не задана организация")

    async def ensure_public_link(
        self, org: Organization, channel: TelegramChannelDTO
    ) -> tuple[Public, PublicSocialLink]:
        network_result = await self.db.execute(select(SocialNetwork).where(SocialNetwork.code == "telegram"))
        network = network_result.scalar_one_or_none()
        if network is None:
            network = SocialNetwork(code="telegram", name="Telegram", description="Telegram")
            self.db.add(network)
            await self.db.flush()

        link_result = await self.db.execute(
            select(PublicSocialLink)
            .join(Public)
            .where(Public.organization_id == org.id)
            .where(PublicSocialLink.social_network_id == network.id)
            .where(PublicSocialLink.external_public_id == channel.id)
        )
        link = link_result.scalar_one_or_none()
        if link is not None:
            public_result = await self.db.execute(select(Public).where(Public.id == link.public_id))
            public = public_result.scalar_one()
            link.url = channel.canonical_url
            link.title = channel.title
            link.is_active = True
            return public, link

        public_result = await self.db.execute(
            select(Public).where(Public.organization_id == org.id, Public.name == channel.title)
        )
        public = public_result.scalar_one_or_none()
        if public is None:
            public = Public(organization_id=org.id, name=channel.title, is_active=True)
            self.db.add(public)
            await self.db.flush()

        link = PublicSocialLink(
            public_id=public.id,
            social_network_id=network.id,
            title=channel.title,
            url=channel.canonical_url,
            external_public_id=channel.id,
            is_primary=True,
            is_active=True,
        )
        self.db.add(link)
        await self.db.flush()
        return public, link

    async def upsert_publication(
        self,
        *,
        organization: Organization,
        public: Public,
        link: PublicSocialLink,
        user: User,
        message: TelegramMessageDTO,
    ) -> Publication:
        source = await get_or_create_data_source(
            self.db,
            source_type="api",
            name="telegram_mtproto",
            description="Импорт постов и комментариев Telegram через MTProto",
            configuration={"platform": "telegram"},
        )
        external_id = str(message.id)
        result = await self.db.execute(
            select(Publication).where(
                Publication.public_social_link_id == link.id,
                Publication.external_post_id == external_id,
            )
        )
        publication = result.scalar_one_or_none()
        content_type = ContentTypeEnum(message.content_type)
        url = f"{link.url}/{message.id}"
        if publication is not None:
            post_result = await self.db.execute(select(Post).where(Post.id == publication.post_id))
            post = post_result.scalar_one()
            post.text_final = message.text
            post.summary = message.text[:500] or None
            post.published_at = message.published_at
            post.content_type = content_type
            post.source_id = source.id
            publication.url = url
            publication.published_at = message.published_at
            publication.content_type = content_type
            publication.status = PublicationStatusEnum.published
            publication.last_synced_at = datetime.now(timezone.utc)
        else:
            title = (message.text.split("\n", 1)[0] if message.text else "(без текста)")[:255]
            post = Post(
                organization_id=organization.id,
                public_id=public.id,
                author_id=user.id,
                title=title,
                text_final=message.text,
                summary=message.text[:500] or None,
                origin=PostOriginEnum.parsed,
                content_type=content_type,
                status=PublicationStatusEnum.published,
                published_at=message.published_at,
                source_id=source.id,
            )
            self.db.add(post)
            await self.db.flush()
            publication = Publication(
                post_id=post.id,
                public_social_link_id=link.id,
                external_post_id=external_id,
                url=url,
                status=PublicationStatusEnum.published,
                content_type=content_type,
                published_at=message.published_at,
                last_synced_at=datetime.now(timezone.utc),
            )
            self.db.add(publication)
            await self.db.flush()
        await sync_post_tags(self.db, post, ["telegram", "parsed", message.content_type])
        await self._upsert_post_metric(publication, message)
        return publication

    async def upsert_comments(
        self, publication: Publication, post_id: int, comments: list[TelegramCommentDTO]
    ) -> int:
        saved = 0
        dedup = await load_comment_dedup_state(self.db, publication.id)
        parent_map = dict(dedup.by_external_id)
        # Telegram возвращает новые сообщения первыми; родитель должен быть
        # сохранён до ответа, иначе parent_comment_id теряется.
        for raw in sorted(comments, key=lambda item: item.id):
            external_id = f"{post_id}:{raw.id}"
            duplicate = dedup.duplicate_id(
                external_id=external_id,
                author_external_id=raw.author_id,
                text=raw.text,
            )
            if duplicate is not None:
                parent_map[external_id] = duplicate
                dedup.by_external_id[external_id] = duplicate
                continue
            parent_external = f"{post_id}:{raw.parent_id}" if raw.parent_id else None
            comment = Comment(
                publication_id=publication.id,
                parent_comment_id=parent_map.get(parent_external) if parent_external else None,
                external_id=external_id,
                text=raw.text,
                author_name=raw.author_name,
                author_external_id=raw.author_id,
                comment_date=raw.published_at,
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
                author_external_id=raw.author_id,
                text=raw.text,
            )
            saved += 1
        return saved

    async def upsert_public_metric(
        self, link: PublicSocialLink, channel: TelegramChannelDTO, messages: list[TelegramMessageDTO]
    ) -> None:
        today = datetime.now(timezone.utc).date()
        totals = {
            "views": sum(item.views for item in messages),
            "comments": sum(item.comments_count for item in messages),
            "reposts": sum(item.forwards for item in messages),
        }
        result = await self.db.execute(
            select(PublicMetric).where(
                PublicMetric.public_social_link_id == link.id,
                PublicMetric.period == MetricPeriodEnum.day,
                PublicMetric.metric_date == today,
            )
        )
        metric = result.scalar_one_or_none()
        values = dict(
            subscribers_count=channel.members_count,
            total_posts=len(messages),
            total_views=totals["views"],
            total_likes=0,
            total_comments=totals["comments"],
            total_reposts=totals["reposts"],
            avg_views=(totals["views"] / len(messages)) if messages else 0.0,
            avg_engagement=((totals["comments"] + totals["reposts"]) / totals["views"] * 100.0) if totals["views"] else 0.0,
            organic_reach=(totals["views"] / channel.members_count * 100.0) if channel.members_count else 0.0,
            posting_regularity=float(len(messages)),
            calculated_at=datetime.now(timezone.utc),
        )
        if metric is None:
            self.db.add(PublicMetric(public_social_link_id=link.id, period=MetricPeriodEnum.day, metric_date=today, **values))
        else:
            for key, value in values.items():
                setattr(metric, key, value)

    async def add_ingest_audit_log(
        self, *, user: User, link: PublicSocialLink, posts_imported: int, comments_imported: int
    ) -> None:
        add_action_log(
            self.db,
            user_id=user.id,
            action="telegram_ingest_completed",
            entity_type="public_social_link",
            entity_id=link.id,
            details={"posts_imported": posts_imported, "comments_imported": comments_imported},
        )

    async def commit(self) -> None:
        await self.db.commit()

    async def _upsert_post_metric(self, publication: Publication, message: TelegramMessageDTO) -> None:
        result = await self.db.execute(
            select(PostMetric).where(
                PostMetric.publication_id == publication.id,
                PostMetric.metric_date == message.published_at.date(),
            )
        )
        metric = result.scalar_one_or_none()
        values = dict(
            views=message.views,
            likes=0,
            comments_count=message.comments_count,
            reposts=message.forwards,
            saves=0,
            collected_at=datetime.now(timezone.utc),
        )
        if metric is None:
            self.db.add(PostMetric(publication_id=publication.id, metric_date=message.published_at.date(), **values))
        else:
            for key, value in values.items():
                setattr(metric, key, value)
