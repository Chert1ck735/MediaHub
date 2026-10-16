"""Execute calendar queries against isolated rows; no working database needed."""
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import create_engine, event, insert
from sqlalchemy.orm import Session

from backend.db import Post, Publication, PublicSocialLink, SocialNetwork, Event
from backend.db.enums import PublicationStatusEnum, PostOriginEnum
from backend.modules.calendar.repositories.calendar_repository import CalendarRepository
from backend.modules.calendar.serializers.serializer import CalendarEventSerializer
from backend.modules.calendar.services.event_service import CalendarEventService


@pytest.fixture
def calendar_db():
    engine = create_engine("sqlite://")

    @event.listens_for(engine, "connect")
    def local_day(connection, _):
        connection.create_function("timezone", 2, lambda zone, value: (
            datetime.fromisoformat(value).replace(tzinfo=timezone.utc)
            .astimezone(ZoneInfo(zone)).isoformat(sep=" ")[:19] if value else None
        ))

    for model in (Post, Publication, PublicSocialLink, SocialNetwork, Event):
        model.__table__.create(engine)
    with Session(engine) as session:
        class Adapter:
            async def execute(self, statement):
                return session.execute(statement)
        yield session, CalendarRepository(Adapter())
    engine.dispose()


def seed(session, *, count=1, org=None, day=None, link=None, post_id=None, status="published"):
    org, link = org or uuid4(), link or uuid4()
    day = day or datetime(2026, 9, 7, 1, tzinfo=timezone.utc)
    post_ids = [post_id or uuid4() for _ in range(count)]
    if post_id is None:
        session.execute(insert(Post), [dict(id=pid, organization_id=org, title=f"Post {i}") for i, pid in enumerate(post_ids)])
    ids = [uuid4() for _ in range(count)]
    session.execute(insert(Publication), [dict(id=pid, post_id=post_ids[i], public_social_link_id=link, published_at=day, status=status) for i, pid in enumerate(ids)])
    session.flush()
    return org, link, post_ids, ids


@pytest.mark.asyncio
async def test_preview_counts_publications_and_excludes_deleted_and_other_orgs(calendar_db):
    session, repo = calendar_db
    org, link, posts, _ = seed(session, count=8)
    seed(session, org=org, post_id=posts[0], link=uuid4())
    seed(session, org=org, status="deleted", count=3)
    seed(session, count=4)
    rows = await repo.list_calendar_publications(org, per_day=3)
    assert len(rows) == 3
    assert {total for _, total in rows} == {9}
    filtered = await repo.list_calendar_publications(org, link_ids=[link], per_day=3)
    assert {total for _, total in filtered} == {8}
    assert all(pub.public_social_link_id == link for pub, _ in filtered)


@pytest.mark.asyncio
async def test_same_post_keeps_every_publication_date(calendar_db):
    session, repo = calendar_db
    org, _, posts, _ = seed(session)
    seed(session, org=org, post_id=posts[0], day=datetime(2026, 9, 8, tzinfo=timezone.utc))
    rows = await repo.list_calendar_publications(org, per_day=1)
    assert len(rows) == 2
    assert {pub.published_at.day for pub, _ in rows} == {7, 8}
    assert {total for _, total in rows} == {1}


@pytest.mark.asyncio
async def test_local_midnight_and_scheduled_precedence(calendar_db):
    session, repo = calendar_db
    org, _, _, ids = seed(session, day=datetime(2026, 9, 6, 18, tzinfo=timezone.utc))
    seed(session, org=org, day=datetime(2026, 9, 7, 16, 59, 59, 999000, tzinfo=timezone.utc))
    seed(session, org=org, day=datetime(2026, 9, 7, 17, tzinfo=timezone.utc))
    pub = session.get(Publication, ids[0])
    pub.status = PublicationStatusEnum.scheduled
    pub.scheduled_at = datetime(2026, 9, 8, 1, tzinfo=timezone.utc)
    session.flush()
    rows = await repo.list_calendar_publications(org, timezone_name="Asia/Krasnoyarsk", per_day=2)
    assert sorted(total for _, total in rows) == [1, 2, 2]
    day = await repo.list_calendar_publications(
        org, timezone_name="Asia/Krasnoyarsk", limit=50,
        date_from=datetime(2026, 9, 6, 17, tzinfo=timezone.utc),
        date_to=datetime(2026, 9, 7, 16, 59, 59, 999000, tzinfo=timezone.utc),
    )
    assert len(day) == 1 and day[0][1] == 1


@pytest.mark.asyncio
async def test_all_rows_accessible_beyond_5000_with_stable_pagination(calendar_db):
    session, repo = calendar_db
    org, _, _, ids = seed(session, count=5017)
    window = dict(date_from=datetime(2026, 9, 7), date_to=datetime(2026, 9, 8))
    first = await repo.list_calendar_publications(org, limit=50, **window)
    second = await repo.list_calendar_publications(org, limit=50, offset=50, **window)
    tail = await repo.list_calendar_publications(org, limit=50, offset=5000, **window)
    assert len(first) == len(second) == 50 and len(tail) == 17
    assert not {p.id for p, _ in first} & {p.id for p, _ in second}
    assert {total for _, total in first + tail} == {5017}
    all_rows = await repo.list_calendar_publications(org, **window)
    assert {p.id for p, _ in all_rows} == set(ids)


def test_serializer_uses_publication_identity_status_and_target():
    when = datetime(2026, 9, 7, 18, tzinfo=timezone.utc)
    post = Post(id=uuid4(), title="Shared post", status=PublicationStatusEnum.pending, origin=PostOriginEnum.manual)
    pub = Publication(id=uuid4(), post_id=post.id, public_social_link_id=uuid4(), published_at=when, status=PublicationStatusEnum.published, url="https://vk.com/wall-1_2")
    output = CalendarEventSerializer().from_post(post, publication=pub)
    assert output["id"] == str(pub.id)
    assert output["post_id"] == str(post.id)
    assert output["status"] == "published"
    assert output["date"] == "2026-09-07" and output["start_time"] == "18:00"
    assert output["publication_ids"] == [str(pub.id)]
    post.publications = [pub]
    full_post = CalendarEventSerializer().from_post(post)
    assert full_post["id"] == str(post.id), "Editing must retain the post identity"


@pytest.mark.asyncio
async def test_month_preview_does_not_load_full_post_text(calendar_db):
    session, repo = calendar_db
    org, _, posts, _ = seed(session)
    post = session.get(Post, posts[0])
    post.text_draft = "Large body " * 10000
    session.flush()
    session.expunge_all()
    rows = await repo.list_calendar_publications(org, per_day=3)
    publication = rows[0][0]
    assert "text_draft" not in publication.post.__dict__
    output = CalendarEventSerializer().from_post(publication.post, publication=publication, compact=True)
    assert output["title"] and output["description"] == "" and output["draft"] == ""


@pytest.mark.asyncio
async def test_service_keeps_counts_without_writing_rollups():
    repo = AsyncMock()
    post = Post(id=uuid4(), title="Post", status=PublicationStatusEnum.pending)
    pub = Publication(id=uuid4(), post=post, public_social_link_id=uuid4(), status=PublicationStatusEnum.published, published_at=datetime(2026, 9, 7, tzinfo=timezone.utc))
    repo.list_calendar_publications.return_value = [(pub, 121)]
    repo.fetch_event_pain_links_map.return_value = {}
    result = await CalendarEventService(AsyncMock(), repository=repo).list_events(SimpleNamespace(organization_id=uuid4()))
    assert result[0]["day_total"] == 121
    assert post.status == PublicationStatusEnum.pending
    repo.commit.assert_not_called()
