from __future__ import annotations

from backend.modules.posts.schema import PublicationResponse


def serialize_publication(publication) -> PublicationResponse:
    public_social_link = publication.__dict__.get("public_social_link")
    social_network = public_social_link.__dict__.get("social_network") if public_social_link else None
    platform = (social_network.code if social_network else None) or "unknown"
    return PublicationResponse(
        id=str(publication.id),
        post_id=str(publication.post_id),
        public_social_link_id=str(publication.public_social_link_id),
        platform=platform,
        public_title=public_social_link.title if public_social_link else None,
        public_url=public_social_link.url if public_social_link else None,
        status=publication.status.value,
        scheduled_at=publication.scheduled_at.isoformat() if publication.scheduled_at else None,
        published_at=publication.published_at.isoformat() if publication.published_at else None,
        external_post_id=publication.external_post_id,
        url=publication.url,
        error_message=publication.error_message,
    )
