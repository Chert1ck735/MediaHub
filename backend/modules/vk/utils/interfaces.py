"""Интерфейсы VK-модуля."""

from datetime import datetime
from pathlib import Path
from typing import Protocol, Any, Callable, Iterable, TYPE_CHECKING

from backend.db import SocialNetwork, Organization, User, Public, PublicSocialLink, Publication, Post
from backend.modules.vk.dto.dto import CreateVkPostDTO, EditVkPostDTO, UploadPhotoDTO, VkLinkRef, FetchPostsResultDTO, \
    ParsedVkPostDTO, IngestResult

if TYPE_CHECKING:
    from backend.modules.jobs.interfaces import ProgressReporterProtocol


class VkApiClientProtocol(Protocol):
    """Контракт низкоуровневого клиента VK API."""

    def call(self, method: str, params: dict[str, Any]) -> dict[str, Any]: ...
    def resolve_screen_name(self, screen_name: str) -> dict[str, Any]: ...
    def get_group(self, group_ref: str | int) -> dict[str, Any]: ...
    def get_user(self, user_id: int | str) -> dict[str, Any]: ...
    def get_user_followers_count(self, user_id: int | str) -> int: ...
    def wall_get(self, *, owner_id: int | None = None, domain: str | None = None, count: int = 20, offset: int = 0, extended: int = 0) -> dict[str, Any]: ...
    def wall_get_by_id(self, owner_id: int, post_id: int) -> dict[str, Any]: ...
    def fetch_all_wall(self, *, owner_id: int | None = None, domain: str | None = None, max_posts: int | None = 100, date_from: datetime | None = None, date_to: datetime | None = None, on_progress: "Callable[[int, int | None], None] | None" = None) -> list[dict[str, Any]]: ...
    def fetch_all_comments(self, owner_id: int, post_id: int, *, max_comments: int = 500) -> list[dict[str, Any]]: ...


class VkLinkParserProtocol(Protocol):
    """Контракт парсера VK-ссылок."""

    def parse(self, raw: str) -> VkLinkRef: ...


class VkPostingServiceProtocol(Protocol):
    """Контракт сервиса публикации/редактирования/удаления постов."""

    def create_post(self, dto: CreateVkPostDTO) -> int: ...
    def edit_post(self, dto: EditVkPostDTO) -> bool: ...
    def delete_post(self, post_id: int, owner_id: int | None = None) -> bool: ...
    def upload_wall_photo(self, dto: UploadPhotoDTO) -> str: ...
    def post_url(self, post_id: int, owner_id: int | None = None) -> str: ...


class VkWallParserServiceProtocol(Protocol):
    """Контракт сервиса чтения стены и преобразования постов."""

    def fetch_posts(self, url: str, max_posts: int | None = None) -> FetchPostsResultDTO: ...
    def parse_post(self, post: dict[str, Any]) -> ParsedVkPostDTO: ...
    def save_posts_to_csv(self, posts: list[dict[str, Any]], filename: Path | None = None) -> Path: ...


class VkPublicServiceProtocol(Protocol):
    """Контракт сервиса выбора дефолтного VK-паблика."""

    async def get_default_public(self, user: User) -> PublicSocialLink | None: ...


class VkIngestionServiceProtocol(Protocol):
    """Контракт сервиса импорта VK-ссылки."""

    async def ingest_link(
            self,
            user: User,
            raw_url: str,
            *,
            max_posts: int | None = None,
            fetch_comments: bool = True,
            date_from: datetime | None = None,
            date_to: datetime | None = None,
            reporter: "ProgressReporterProtocol | None" = None,
    ) -> IngestResult: ...


class VkIngestionRepositoryProtocol(Protocol):
    """Контракт репозитория VK-импорта."""

    async def get_or_create_vk_network(self) -> SocialNetwork: ...
    async def resolve_organization(self, user: User) -> Organization: ...
    async def get_or_create_public(self, org: Organization, name: str, description: str | None) -> Public: ...
    async def get_or_create_social_link(self, public: Public, network: SocialNetwork, *, url: str, external_public_id: str, title: str | None) -> PublicSocialLink: ...
    async def upsert_post_with_publication(self, *, org: Organization, public: Public, link: PublicSocialLink, user: User, vk_post: dict[str, Any]) -> tuple[Post, Publication]: ...
    async def upsert_post_metric(self, publication: Publication, vk_post: dict[str, Any]) -> None: ...
    async def upsert_comments(self, publication: Publication, vk_comments: Iterable[dict[str, Any]]) -> int: ...
    async def upsert_public_metric(self, link: PublicSocialLink, *, members: int, posts_total: int, sum_views: int, sum_likes: int, sum_comments: int, sum_reposts: int) -> None: ...
    async def commit(self) -> None: ...
    async def rollback(self) -> None: ...

    async def add_ingest_audit_log(self, user, link, public, mode, posts_imported, comments_imported):
        pass


class VkAnalyticsRefreshServiceProtocol(Protocol):
    """Контракт обновления VK-аналитики после импорта."""

    async def refresh(self, user: User) -> None:
        """
        Пересобирает VK-аналитику организации.

        Используется после успешного импорта:
        - очищает старые VK snapshot'ы;
        - пересчитывает боли;
        - пересобирает аналитические агрегаты.
        """
        ...
