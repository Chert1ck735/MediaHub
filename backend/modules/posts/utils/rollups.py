"""Пересчет агрегированных полей поста по его публикациям."""

from datetime import datetime, timezone

from backend.db.enums import PublicationStatusEnum
from backend.db.posts import Post


def refresh_post_rollups(post: Post) -> None:
    """Обновляет scheduled_at, published_at и status на основе публикаций поста."""
    now = datetime.now(timezone.utc)
    publications = list(post.__dict__.get("publications") or [])
    future_publications = [
        publication
        for publication in publications
        if publication.scheduled_at
        and publication.scheduled_at >= now
        and publication.status != PublicationStatusEnum.deleted
    ]
    published_publications = [
        publication
        for publication in publications
        if publication.status == PublicationStatusEnum.published and publication.published_at
    ]

    post.scheduled_at = min((publication.scheduled_at for publication in future_publications), default=None)
    post.published_at = max((publication.published_at for publication in published_publications), default=None)
    if published_publications:
        post.status = PublicationStatusEnum.published
    elif future_publications:
        post.status = PublicationStatusEnum.scheduled
    else:
        post.status = PublicationStatusEnum.pending

