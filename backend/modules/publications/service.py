from __future__ import annotations

from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.enums import ContentTypeEnum, PublicationStatusEnum
from backend.db.posts import Post
from backend.db.public_social_links import PublicSocialLink
from backend.db.publications import Publication
from backend.db.users import User
from backend.modules.audit_utils import add_action_log
from backend.modules.posts.service import load_post_for_user, refresh_post_rollups
from backend.modules.publications.repositories.publication_repository import (
    PublicationRepository,
)


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _normalize_status(value: str | None) -> PublicationStatusEnum:
    if not value:
        return PublicationStatusEnum.scheduled
    return PublicationStatusEnum(value)


async def resolve_public_social_link_for_platform(
    db: AsyncSession,
    organization_id,
    platform: str,
) -> PublicSocialLink | None:
    return await PublicationRepository(db).resolve_active_link_for_platform(
        organization_id,
        platform,
    )


async def create_publication(
    db: AsyncSession,
    post_id: str,
    user: User,
    *,
    platform: str,
    public_social_link_id: str | None = None,
    scheduled_at: str | None = None,
    status_value: str = "scheduled",
    external_post_id: str | None = None,
    url: str | None = None,
    published_at: str | None = None,
    error_message: str | None = None,
) -> Post:
    post = await load_post_for_user(db, post_id, user.organization_id)
    if not post:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Пост не найден")

    repository = PublicationRepository(db)
    link = await repository.resolve_active_link_for_user(
        user.organization_id,
        public_social_link_id=public_social_link_id,
        platform=platform,
    )
    if not link:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Для площадки {platform} не найдена активная public_social_link",
        )

    publication = Publication(
        post=post,
        public_social_link_id=link.id,
        external_post_id=external_post_id,
        url=url,
        status=_normalize_status(status_value),
        content_type=ContentTypeEnum.text,
        scheduled_at=_parse_dt(scheduled_at),
        published_at=_parse_dt(published_at),
        error_message=error_message,
    )
    publication.public_social_link = link
    db.add(publication)
    await db.flush()
    add_action_log(
        db,
        user_id=user.id,
        action="publication_created",
        entity_type="publication",
        entity_id=publication.id,
        details={"post_id": post.id, "platform": platform, "status": publication.status.value},
    )
    await refresh_post_rollups(db, post)
    await db.commit()
    return await load_post_for_user(db, str(post.id), user.organization_id, with_publications=True)


async def update_publication(
    db: AsyncSession,
    publication_id: str,
    user: User,
    *,
    platform: str | None = None,
    public_social_link_id: str | None = None,
    scheduled_at: str | None = None,
    status_value: str | None = None,
    external_post_id: str | None = None,
    url: str | None = None,
    published_at: str | None = None,
    error_message: str | None = None,
) -> Post:
    repository = PublicationRepository(db)
    publication = await repository.get_for_organization(publication_id, user.organization_id)
    if not publication:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Публикация не найдена")

    if platform is not None or public_social_link_id is not None:
        link = await repository.resolve_active_link_for_user(
            user.organization_id,
            public_social_link_id=public_social_link_id,
            platform=platform,
        )
        if not link:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Для площадки {platform} не найдена активная public_social_link",
            )
        publication.public_social_link_id = link.id
        publication.public_social_link = link
    if scheduled_at is not None:
        publication.scheduled_at = _parse_dt(scheduled_at)
    if status_value is not None:
        publication.status = _normalize_status(status_value)
    if external_post_id is not None:
        publication.external_post_id = external_post_id
    if url is not None:
        publication.url = url
    if published_at is not None:
        publication.published_at = _parse_dt(published_at)
    if error_message is not None:
        publication.error_message = error_message

    add_action_log(
        db,
        user_id=user.id,
        action="publication_updated",
        entity_type="publication",
        entity_id=publication.id,
        details={"post_id": publication.post_id, "status": publication.status.value},
    )
    await refresh_post_rollups(db, publication.post)
    await db.commit()
    return await load_post_for_user(db, str(publication.post_id), user.organization_id, with_publications=True)


async def delete_publication(db: AsyncSession, publication_id: str, user: User) -> Post:
    publication = await PublicationRepository(db).get_for_organization(
        publication_id,
        user.organization_id,
    )
    if not publication:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Публикация не найдена")

    post = publication.post
    publications = post.__dict__.get("publications")
    if isinstance(publications, list):
        post.publications = [item for item in publications if item.id != publication.id]
    add_action_log(
        db,
        user_id=user.id,
        action="publication_deleted",
        entity_type="publication",
        entity_id=publication.id,
        details={"post_id": publication.post_id},
    )
    await db.delete(publication)
    await db.flush()
    await refresh_post_rollups(db, post)
    await db.commit()
    return await load_post_for_user(db, str(post.id), user.organization_id, with_publications=True)
