"""Интеграционные тесты ветвей классификации/бакетинга build() на media_test."""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import select

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
from backend.modules.analytics.services.vk_snapshot_builder import VkSnapshotBuilder

pytestmark = pytest.mark.integration

ROAD_COMPLAINT = "Дорога вся разбита, сплошные ямы, это ужас и безобразие"


async def _seed(session, comments: list[tuple[str, str]]):
    """comments: список (text, author_external_id). Возвращает stub-user с organization_id."""
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

    publication = Publication(
        post_id=post.id,
        public_social_link_id=link.id,
        url="https://vk.com/wall-1_1",
    )
    session.add(publication)
    await session.flush()

    for text, ext_id in comments:
        session.add(
            Comment(
                publication_id=publication.id,
                text=text,
                author_external_id=ext_id,
                parsed_at=now,
                created_at=now,
            )
        )
        await session.flush()

    return SimpleNamespace(id=None, organization_id=org.id)


@pytest.mark.asyncio(loop_scope="session")
async def test_build_dedups_copypaste(db_session):
    # два одинаковых коммента от разных пользователей → копипаста схлопывается в 1 упоминание
    user = await _seed(db_session, [(ROAD_COMPLAINT, "101"), (ROAD_COMPLAINT, "102")])

    builder = VkSnapshotBuilder(db_session)
    await builder.build(user, force_reclassify=False)

    pains = (
        await db_session.execute(select(Pain).where(Pain.organization_id == user.organization_id))
    ).scalars().all()
    assert len(pains) == 1
    assert pains[0].mentions_count == 1  # дубль не считается дважды

    comment_pains = (await db_session.execute(select(CommentPain))).scalars().all()
    assert len(comment_pains) == 1


@pytest.mark.asyncio(loop_scope="session")
async def test_build_excludes_community_authored(db_session):
    # комментарий самого сообщества (author_external_id отрицателен) → не порождает боль
    user = await _seed(db_session, [(ROAD_COMPLAINT, "-1")])

    builder = VkSnapshotBuilder(db_session)
    await builder.build(user, force_reclassify=False)

    pains = (
        await db_session.execute(select(Pain).where(Pain.organization_id == user.organization_id))
    ).scalars().all()
    assert len(pains) == 0
