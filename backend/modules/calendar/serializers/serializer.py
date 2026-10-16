from datetime import timezone
from typing import Any

from backend.db import Post, Publication
from backend.modules.calendar.utils.errors import CalendarNotFoundError
from backend.modules.calendar.utils.utils import effective_publication_dt
from backend.modules.posts.content import extract_post_tone


def _publication_label(publication: Publication) -> str:
    """Возвращает человекочитаемое имя площадки публикации."""

    link = publication.__dict__.get("public_social_link")
    network = link.__dict__.get("social_network") if link else None

    if link is not None:
        title = (link.title or "").strip()
        url = (link.url or "").strip()
        if title:
            return title
        if url:
            return url.replace("https://", "").replace("http://", "")

    return network.code.upper() if network else "VK"


class CalendarEventSerializer:
    """Преобразует ORM-модели календаря в API-ответ."""

    def from_post(
        self,
        post: Post,
        pain_links: list[dict[str, str]] | None = None,
        *, publication: Publication | None = None,
        compact: bool = False,
    ) -> dict[str, Any]:
        """Преобразует Post в календарное событие API."""
        publications = [publication] if publication is not None else list(post.__dict__.get("publications") or [])
        publications = [
            publication
            for publication in publications
            if publication.status.value != "deleted"
        ]

        if not publications:
            raise CalendarNotFoundError("Событие не найдено")

        publications.sort(key=effective_publication_dt)
        effective_dt = effective_publication_dt(publications[0])
        targets: list[str] = []

        for target_publication in publications:
            label = _publication_label(target_publication)
            if label not in targets:
                targets.append(label)

        info_event = post.__dict__.get("event")
        pain_links = pain_links or []

        return {
            "id": str(publication.id if publication is not None else post.id),
            "origin": post.origin.value if post.origin else None,
            "title": post.title or "(без названия)",
            "date": effective_dt.astimezone(timezone.utc).date().isoformat(),
            "start_time": effective_dt.astimezone(timezone.utc).strftime("%H:%M"),
            "end_time": effective_dt.astimezone(timezone.utc).strftime("%H:%M"),
            "description": "" if compact else post.text_draft or "",
            "status": publication.status.value if publication is not None else post.status.value,
            "platforms": targets or ["VK"],
            "draft": "" if compact else post.text_generated or "",
            "tone": "" if compact else extract_post_tone(post),
            "post_type": "",
            "post_id": str(post.id),
            "info_event_id": str(post.event_id) if post.event_id else None,
            "info_event_title": info_event.title if info_event else None,
            "inherited_pain_ids": [link["pain_id"] for link in pain_links],
            "inherited_pain_titles": [link["pain_title"] for link in pain_links],
            "publication_ids": [str(publication.id) for publication in publications],
            "public_social_link_ids": [
                str(publication.public_social_link_id)
                for publication in publications
            ],
            "publication_urls": [publication.url for publication in publications],
        }
