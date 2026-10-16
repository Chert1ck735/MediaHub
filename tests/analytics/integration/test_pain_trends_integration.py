"""Интеграционный тест PainTrendsService на реальной БД (media_test)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from backend.db import (
    Comment,
    CommentPain,
    Organization,
    Pain,
    Post,
    Public,
    PublicSocialLink,
    Publication,
    SocialNetwork,
)
from backend.db.enums import OrgType
from backend.modules.analytics.services.pain_trends_service import PainTrendsService

pytestmark = pytest.mark.integration


async def _seed_pain_with_comments(session, created_dates: list[datetime]):
    """Засевает минимальный граф org→public→link→post→publication→comments→pain."""

    now = datetime.now(timezone.utc)

    org = Organization(name="Test Org", type=OrgType.government)
    session.add(org)
    await session.flush()

    network = SocialNetwork(code="vk", name="VK")
    session.add(network)
    await session.flush()

    public = Public(organization_id=org.id, name="Test Public")
    session.add(public)
    await session.flush()

    link = PublicSocialLink(
        public_id=public.id,
        social_network_id=network.id,
        url="https://vk.com/club1",
        external_public_id="1",
    )
    session.add(link)
    await session.flush()

    post = Post(organization_id=org.id)
    session.add(post)
    await session.flush()

    publication = Publication(post_id=post.id, public_social_link_id=link.id)
    session.add(publication)
    await session.flush()

    pain = Pain(organization_id=org.id, title="ЖКХ", category="ЖКХ и городская среда")
    session.add(pain)
    await session.flush()

    for created in created_dates:
        comment = Comment(
            publication_id=publication.id,
            text="комментарий",
            parsed_at=now,
            created_at=created,
        )
        session.add(comment)
        await session.flush()
        session.add(CommentPain(comment_id=comment.id, pain_id=pain.id))

    await session.flush()
    return org.id, pain.id


@pytest.mark.asyncio(loop_scope="session")
async def test_pain_trends_daily_buckets_for_week(db_session):
    """Период «неделя» → деление в один день, последний бакет не обрезан."""

    now = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

    org_id, pain_id = await _seed_pain_with_comments(
        db_session,
        [
            now + timedelta(hours=5),          # последний день
            now + timedelta(hours=9),          # последний день
            now - timedelta(days=1, hours=3),  # день назад
            now - timedelta(days=3, hours=3),  # три дня назад
        ],
    )

    user = SimpleNamespace(organization_id=org_id)
    service = PainTrendsService(db_session)

    result = await service.list_trends(user, since=now - timedelta(days=7))

    assert len(result) == 1
    item = result[0]
    assert item.pain_id == str(pain_id)
    assert item.bucket_days == 1
    assert len(item.counts) == 7
    # Последний день полноценный: оба коммента попали в хвост, а не «утекли».
    assert item.counts[-1] == 2
    assert item.counts[-2] == 1
    assert sum(item.counts) == 4


@pytest.mark.asyncio(loop_scope="session")
async def test_pain_trends_weekly_buckets_for_quarter(db_session):
    """Период «3 месяца» → деление в неделю."""

    now = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

    org_id, pain_id = await _seed_pain_with_comments(
        db_session,
        [now - timedelta(days=offset, hours=2) for offset in (0, 1, 10, 40)],
    )

    user = SimpleNamespace(organization_id=org_id)
    service = PainTrendsService(db_session)

    result = await service.list_trends(user, since=now - timedelta(days=90))

    assert len(result) == 1
    item = result[0]
    assert item.bucket_days == 7
    assert len(item.counts) == 13
    assert item.counts[-1] == 2  # текущая неделя: два свежих коммента
    assert sum(item.counts) == 4
