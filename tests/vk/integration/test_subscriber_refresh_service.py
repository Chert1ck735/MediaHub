from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from backend.db import Organization, Public, PublicMetric, PublicSocialLink, SocialNetwork
from backend.db.enums import MetricPeriodEnum, OrgType
from backend.modules.vk.dto.dto import VkOwnerInfoDTO
from backend.modules.vk.services.subscriber_refresh_service import VkSubscriberRefreshService


def make_owner(owner_id: int, members_count: int) -> VkOwnerInfoDTO:
    return VkOwnerInfoDTO(
        name="Owner",
        description=None,
        screen=f"id{abs(owner_id)}",
        canonical_url=f"https://vk.com/id{abs(owner_id)}",
        external_public_id=str(abs(owner_id)),
        owner_id=owner_id,
        members_count=members_count,
    )


class FakeOwnerResolver:
    def resolve_screen_name(self, ref):
        return ref

    def resolve_community_owner(self, ref):
        return make_owner(-123, 1000)

    def resolve_profile_owner(self, ref):
        return make_owner(42, 77)

    def resolve_post_owner(self, ref):
        return make_owner(ref.owner_id, 0)


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_refresh_all_updates_vk_subscribers_without_resetting_existing_metrics(db_session):
    org = Organization(name="Test org", type=OrgType.government)
    network = SocialNetwork(code="vk", name="VK")
    group_public = Public(organization=org, name="Group", description=None, is_active=True)
    profile_public = Public(organization=org, name="Profile", description=None, is_active=True)
    db_session.add_all([org, network, group_public, profile_public])
    await db_session.flush()

    group_link = PublicSocialLink(
        public_id=group_public.id,
        social_network_id=network.id,
        title="Group",
        url="https://vk.com/club123",
        external_public_id="123",
        is_active=True,
    )
    profile_link = PublicSocialLink(
        public_id=profile_public.id,
        social_network_id=network.id,
        title="Profile",
        url="https://vk.com/id42",
        external_public_id="42",
        is_active=True,
    )
    db_session.add_all([group_link, profile_link])
    await db_session.flush()

    today = datetime.now(timezone.utc).date()
    db_session.add(
        PublicMetric(
            public_social_link_id=group_link.id,
            period=MetricPeriodEnum.day,
            metric_date=today,
            subscribers_count=10,
            total_posts=2,
            total_views=500,
            total_likes=20,
            total_comments=5,
            total_reposts=1,
            avg_views=250.0,
            avg_engagement=5.2,
            organic_reach=5000.0,
            posting_regularity=2.0,
            calculated_at=datetime.now(timezone.utc),
        )
    )
    await db_session.flush()

    stats = await VkSubscriberRefreshService(
        db_session,
        api_client=SimpleNamespace(),
        owner_resolver=FakeOwnerResolver(),
    ).refresh_all()

    assert stats.links_total == 2
    assert stats.links_updated == 2
    assert stats.links_failed == 0

    group_metric = (
        await db_session.execute(
            select(PublicMetric).where(PublicMetric.public_social_link_id == group_link.id)
        )
    ).scalar_one()
    assert group_metric.subscribers_count == 1000
    assert group_metric.total_views == 500
    assert group_metric.organic_reach == 50.0

    profile_metrics = (
        await db_session.execute(
            select(PublicMetric).where(PublicMetric.public_social_link_id == profile_link.id)
        )
    ).scalars().all()
    assert len(profile_metrics) == 1
    assert profile_metrics[0].subscribers_count == 77
