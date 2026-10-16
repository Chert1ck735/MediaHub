"""Интеграционные тесты пайплайна классификации (C1 запитка очереди, C2 возврат зависших)."""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from backend.db import Organization, OrgType, SocialNetwork, Public, PublicSocialLink, Post, Publication, Comment
from backend.db.comment_analysis import CommentAnalysis
from backend.modules.analytics.classification import requeue_low_confidence, reset_stale_processing
from backend.modules.vk.repositories.ingestion_repository import VkIngestionRepository

pytestmark = pytest.mark.integration


async def _seed_publication(db) -> Publication:
    """Создаёт минимальную цепочку Organization→Public→Link→Post→Publication."""
    org = Organization(name="Test org", type=OrgType.government)
    db.add(org)
    await db.flush()
    network = SocialNetwork(code="vk", name="VK", description="ВКонтакте")
    public = Public(organization_id=org.id, name="P", description="d", is_active=True)
    db.add_all([network, public])
    await db.flush()
    link = PublicSocialLink(
        public_id=public.id,
        social_network_id=network.id,
        title="t",
        url=f"https://vk.com/{uuid.uuid4()}",
        external_public_id="1",
        is_primary=True,
        is_active=True,
    )
    post = Post(organization_id=org.id)
    db.add_all([link, post])
    await db.flush()
    publication = Publication(post_id=post.id, public_social_link_id=link.id)
    db.add(publication)
    await db.flush()
    return publication


@pytest.mark.asyncio(loop_scope="session")
async def test_ingested_comment_is_queued_pending(db_session):
    publication = await _seed_publication(db_session)
    repo = VkIngestionRepository(db_session)

    saved = await repo.upsert_comments(
        publication,
        [{"id": 111, "text": "Плохие дороги", "from_id": 5, "date": 1_700_000_000}],
    )
    await db_session.flush()

    assert saved == 1
    states = (
        await db_session.execute(
            select(CommentAnalysis.classification_state)
            .join(Comment, Comment.id == CommentAnalysis.comment_id)
            .where(Comment.publication_id == publication.id)
        )
    ).scalars().all()
    assert states == ["pending"]


@pytest.mark.asyncio(loop_scope="session")
async def test_reset_stale_processing_requeues_only_old(db_session):
    publication = await _seed_publication(db_session)
    now = datetime.now(timezone.utc)
    c_old = Comment(publication_id=publication.id, external_id="a", text="x", parsed_at=now, is_deleted=False)
    c_fresh = Comment(publication_id=publication.id, external_id="b", text="y", parsed_at=now, is_deleted=False)
    db_session.add_all([c_old, c_fresh])
    await db_session.flush()

    stale = CommentAnalysis(
        comment_id=c_old.id,
        classification_state="processing",
        updated_at=now - timedelta(hours=2),
    )
    recent = CommentAnalysis(
        comment_id=c_fresh.id,
        classification_state="processing",
        updated_at=now,
    )
    db_session.add_all([stale, recent])
    await db_session.commit()

    requeued = await reset_stale_processing(db_session, older_than_seconds=1800)

    assert requeued == 1
    await db_session.refresh(stale)
    await db_session.refresh(recent)
    assert stale.classification_state == "pending"
    assert recent.classification_state == "processing"


@pytest.mark.asyncio(loop_scope="session")
async def test_low_confidence_requeue_ignores_llm_review_and_skipped(db_session):
    publication = await _seed_publication(db_session)
    now = datetime.now(timezone.utc)
    c_llm = Comment(publication_id=publication.id, external_id="llm", text="x", parsed_at=now, is_deleted=False)
    c_skipped = Comment(publication_id=publication.id, external_id="skip", text="y", parsed_at=now, is_deleted=False)
    c_rule = Comment(publication_id=publication.id, external_id="rule", text="z", parsed_at=now, is_deleted=False)
    db_session.add_all([c_llm, c_skipped, c_rule])
    await db_session.flush()

    llm_review = CommentAnalysis(
        comment_id=c_llm.id,
        classification_state="done",
        classification_source="llm_needs_review",
        model_version="qwen",
    )
    skipped_rule = CommentAnalysis(
        comment_id=c_skipped.id,
        classification_state="skipped",
        classification_source="needs_review",
        model_version="vk_rule_based_v2",
    )
    rule_review = CommentAnalysis(
        comment_id=c_rule.id,
        classification_state="done",
        classification_source="needs_review",
        model_version="vk_rule_based_v2",
    )
    db_session.add_all([llm_review, skipped_rule, rule_review])
    await db_session.commit()

    requeued = await requeue_low_confidence(db_session)

    assert requeued == 1
    await db_session.refresh(llm_review)
    await db_session.refresh(skipped_rule)
    await db_session.refresh(rule_review)
    assert llm_review.classification_state == "done"
    assert skipped_rule.classification_state == "skipped"
    assert rule_review.classification_state == "pending"
