"""Refresh VK subscribers count for already imported links."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db import Public, PublicMetric, PublicSocialLink, SocialNetwork
from backend.db.enums import MetricPeriodEnum
from backend.db.organizations import Organization
from backend.modules.jobs.services.progress_reporter import ProgressReporter
from backend.modules.vk.dto.dto import VkLinkType
from backend.modules.vk.links.link_parser import VkLinkParser
from backend.modules.vk.services.owner_resolver_service import VkOwnerResolverService
from backend.modules.vk.utils.api_client import VkApiClient
from backend.modules.vk.utils.errors import IngestionError, InvalidVkLinkError, VkApiError
from backend.modules.vk.utils.interfaces import VkApiClientProtocol


@dataclass
class SubscriberRefreshStats:
    links_total: int = 0
    links_updated: int = 0
    links_failed: int = 0
    errors: list[dict[str, str]] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "links_total": self.links_total,
            "links_updated": self.links_updated,
            "links_failed": self.links_failed,
            "errors": self.errors or [],
        }


class VkSubscriberRefreshService:
    """Обновляет сегодняшний PublicMetric.subscribers_count по активным ссылкам VK."""

    def __init__(
        self,
        db: AsyncSession,
        *,
        api_client: VkApiClientProtocol | None = None,
        link_parser: VkLinkParser | None = None,
        owner_resolver: VkOwnerResolverService | None = None,
    ) -> None:
        self.db = db
        self.api_client = api_client or VkApiClient()
        self.link_parser = link_parser or VkLinkParser()
        self.owner_resolver = owner_resolver or VkOwnerResolverService(self.api_client)

    async def refresh_all(
        self,
        *,
        progress: ProgressReporter | None = None,
    ) -> SubscriberRefreshStats:
        links = await self._list_active_vk_links()
        stats = SubscriberRefreshStats(links_total=len(links), errors=[])
        if progress is not None:
            await progress.update(total=len(links), done=0, message="Обновление подписчиков VK…")

        for index, link in enumerate(links, start=1):
            if progress is not None:
                progress.raise_if_cancelled()
            try:
                subscribers = await asyncio.to_thread(self._resolve_subscribers_count, link.url)
                await self._upsert_today_subscribers(link, subscribers)
                stats.links_updated += 1
            except (InvalidVkLinkError, IngestionError, VkApiError, ValueError) as exc:
                stats.links_failed += 1
                stats.errors.append({"link_id": str(link.id), "url": link.url, "error": str(exc)})
            if progress is not None:
                await progress.update(
                    done=index,
                    message=f"Обновлено подписчиков VK: {stats.links_updated}/{len(links)}",
                )

        await self.db.commit()
        return stats

    async def _list_active_vk_links(self) -> list[PublicSocialLink]:
        result = await self.db.execute(
            select(PublicSocialLink)
            .join(SocialNetwork, SocialNetwork.id == PublicSocialLink.social_network_id)
            .join(Public, Public.id == PublicSocialLink.public_id)
            .join(Organization, Organization.id == Public.organization_id)
            .where(SocialNetwork.code == "vk")
            .where(PublicSocialLink.is_active.is_(True))
            .where(Public.is_active.is_(True))
            .where(Organization.is_active.is_(True))
            .order_by(PublicSocialLink.created_at.asc())
        )
        return list(result.scalars().all())

    def _resolve_subscribers_count(self, url: str) -> int:
        ref = self.link_parser.parse(url)
        if ref.type == VkLinkType.COMMUNITY and ref.domain and ref.owner_id is None:
            ref = self.owner_resolver.resolve_screen_name(ref)

        if ref.type == VkLinkType.COMMUNITY:
            owner = self.owner_resolver.resolve_community_owner(ref)
        elif ref.type == VkLinkType.PROFILE:
            owner = self.owner_resolver.resolve_profile_owner(ref)
        elif ref.type == VkLinkType.POST:
            owner = self.owner_resolver.resolve_post_owner(ref)
        else:
            raise IngestionError(f"Неизвестный тип VK-ссылки: {ref.type}")
        return owner.members_count

    async def _upsert_today_subscribers(self, link: PublicSocialLink, subscribers: int) -> None:
        today = datetime.now(timezone.utc).date()
        now = datetime.now(timezone.utc)
        result = await self.db.execute(
            select(PublicMetric).where(
                PublicMetric.public_social_link_id == link.id,
                PublicMetric.period == MetricPeriodEnum.day,
                PublicMetric.metric_date == today,
            )
        )
        metric = result.scalar_one_or_none()
        if metric is None:
            self.db.add(
                PublicMetric(
                    public_social_link_id=link.id,
                    period=MetricPeriodEnum.day,
                    metric_date=today,
                    subscribers_count=subscribers,
                    total_posts=0,
                    total_views=0,
                    total_likes=0,
                    total_comments=0,
                    total_reposts=0,
                    avg_views=0.0,
                    avg_engagement=0.0,
                    organic_reach=0.0,
                    posting_regularity=0.0,
                    calculated_at=now,
                )
            )
            return

        metric.subscribers_count = subscribers
        metric.organic_reach = (metric.total_views / subscribers * 100.0) if subscribers else 0.0
        metric.calculated_at = now
