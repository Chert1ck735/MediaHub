"""Интеграционный тест VkSnapshotBuilder.build() на реальной БД (media_test)."""
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
    SnapshotPain,
    SocialNetwork,
)
from backend.db.enums import OrgType
from backend.modules.analytics.services.vk_snapshot_builder import VkSnapshotBuilder

pytestmark = pytest.mark.integration


async def _seed_comments(session):
    """Граф org→public→link→post→publication + «дорожные» негативные комменты."""

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

    texts = [
        "Дорога вся разбита, сплошные ямы, это ужас и безобразие",
        "Опять ямы на дороге, ничего не делают, проблема не решается",
        "На дороге яма, когда уже отремонтируют асфальт?",
    ]
    for i, text in enumerate(texts):
        comment = Comment(
            publication_id=publication.id,
            text=text,
            author_external_id=str(100 + i),  # положительный → не сообщество
            parsed_at=now,
            created_at=now,
        )
        session.add(comment)
        await session.flush()

    await session.flush()
    return SimpleNamespace(id=None, organization_id=org.id)


@pytest.mark.asyncio(loop_scope="session")
async def test_build_creates_snapshot_and_pains(db_session):
    user = await _seed_comments(db_session)

    builder = VkSnapshotBuilder(db_session)
    snapshot, stats = await builder.build(user, force_reclassify=False)

    # снапшот создан и сохранён
    assert snapshot.id is not None
    assert snapshot.source_name == "vk_auto_comments"

    # боль «Дороги и транспорт» выделена
    pains = (
        await db_session.execute(
            select(Pain).where(Pain.organization_id == user.organization_id)
        )
    ).scalars().all()
    assert len(pains) >= 1
    assert any("Дороги" in (p.category or "") for p in pains)

    # боли связаны со снапшотом
    snapshot_pains = (
        await db_session.execute(
            select(SnapshotPain).where(SnapshotPain.snapshot_id == snapshot.id)
        )
    ).scalars().all()
    assert len(snapshot_pains) >= 1

    # комментарии привязаны к боли через CommentPain
    comment_pains = (await db_session.execute(select(CommentPain))).scalars().all()
    assert len(comment_pains) >= 1
