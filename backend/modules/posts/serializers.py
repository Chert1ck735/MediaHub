"""Сериализация Post в API-ответы."""

from backend.db.posts import Post
from backend.modules.posts.content import extract_post_tone
from backend.modules.posts.schema import PostResponse
from backend.modules.publications.serializers import serialize_publication


def serialize_post(post: Post) -> PostResponse:
    """Преобразует ORM-пост со связями в PostResponse для API."""
    publications = post.__dict__.get("publications") or []
    strategy_links = post.__dict__.get("strategy_links") or []
    vk_publication = next((publication for publication in publications if publication.external_post_id), None)
    return PostResponse(
        id=str(post.id),
        origin=post.origin.value if post.origin else None,
        title=post.title or "(без названия)",
        text_draft=post.text_draft,
        text_generated=post.text_generated,
        tone=extract_post_tone(post),
        vk_post_id=vk_publication.external_post_id if vk_publication else None,
        vk_wall_url=vk_publication.url if vk_publication else None,
        strategy_id=str(strategy_links[0].strategy_id) if strategy_links else None,
        status=post.status.value,
        scheduled_at=post.scheduled_at.isoformat() if post.scheduled_at else None,
        published_at=post.published_at.isoformat() if post.published_at else None,
        created_at=post.created_at.isoformat(),
        publications=[serialize_publication(publication) for publication in publications],
    )
