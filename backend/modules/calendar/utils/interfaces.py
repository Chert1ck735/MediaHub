"""Интерфейсы календарного модуля."""
from datetime import datetime
from typing import Protocol, Any

from backend.db import Post, Publication, User, PublicSocialLink
from backend.modules.vk.dto.dto import CreateVkPostDTO, EditVkPostDTO


class CalendarRepositoryProtocol(Protocol):
    """Контракт SQL-репозитория календаря."""

    async def list_calendar_publications(
        self, organization_id, *, date_from=None, date_to=None, link_ids=None,
        per_day=None, timezone_name="UTC", limit=None, offset=0,
    ) -> list[tuple[Publication, int]]: ...

    async def list_posts_with_publications(
        self,
        organization_id,
        *,
        date_from=None,
        date_to=None,
        link_ids=None,
        per_day=None,
    ) -> list[Post]: ...

    async def count_publications_by_day(
        self,
        organization_id,
        *,
        date_from=None,
        date_to=None,
        link_ids=None,
    ) -> dict[str, int]: ...
    async def get_calendar_post(self, post_id: str, organization_id) -> Post | None: ...
    async def get_public_social_link(self, link_id: str, organization_id) -> PublicSocialLink | None: ...
    async def fetch_event_pain_links(self, event_id) -> list[dict[str, str]]: ...
    async def fetch_event_pain_links_map(self, event_ids: set) -> dict[Any, list[dict[str, str]]]: ...
    async def add_publication(self, publication: Publication) -> Publication: ...
    async def delete_publication(self, publication: Publication) -> None: ...
    async def flush(self) -> None: ...
    async def commit(self) -> None: ...


class CalendarPostServiceProtocol(Protocol):
    """Контракт сервиса постов календаря."""

    async def create_or_update_post(
            self,
            *,
            user: User,
            post_id: str | None,
            title: str,
            description: str,
            draft: str,
            tone: str
    ) -> Post: ...

    async def require_post(self, post_id: str, organization_id) -> Post: ...
    def fill_post(self, *, post: Post, title: str, description: str, draft: str, tone: str) -> None: ...
    def apply_info_event(self, post: Post, info_event_id: str | None, *, reset_on_invalid: bool) -> None: ...


class CalendarPublicationServiceProtocol(Protocol):
    """Контракт сервиса публикаций календаря."""

    async def resolve_target_link_ids(
            self,
            organization_id,
            platforms: list[str],
            public_social_link_ids: list[str] | None
    ) -> list[str]: ...

    async def upsert_publications(
            self,
            *,
            post: Post,
            organization_id,
            desired_link_ids: list[str],
            ev_status: str,
            when: datetime
    ) -> None: ...

    async def sync_publications(
            self,
            *,
            post: Post,
            organization_id,
            desired_link_ids: list[str],
            ev_status: str, when: datetime
    ) -> None: ...

    async def delete_publications(self, post: Post) -> None: ...


class CalendarVkPostingProtocol(Protocol):
    """Контракт сервиса публикации VK, используемый календарём."""

    def create_post(self, dto: CreateVkPostDTO) -> int: ...
    def edit_post(self, dto: EditVkPostDTO) -> bool: ...
    def delete_post(self, post_id: int, owner_id: int | None = None) -> bool: ...
    def post_url(self, post_id: int, owner_id: int | None = None) -> str: ...


class CalendarSerializerProtocol(Protocol):
    """Контракт сериализации календарного события."""

    def from_post(self, post: Post, pain_links: list[dict[str, str]] | None = None,
                  *, publication: Publication | None = None, compact: bool = False) -> dict[str, Any]: ...
