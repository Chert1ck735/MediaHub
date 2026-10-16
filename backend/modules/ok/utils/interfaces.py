"""Интерфейсы OK-модуля."""

from datetime import datetime
from typing import Any, Callable, Iterable, Protocol, TYPE_CHECKING

from backend.db import (
    Organization,
    Post,
    Public,
    PublicSocialLink,
    Publication,
    SocialNetwork,
    User,
)
from backend.modules.ok.dto.dto import OkIngestResult, OkLinkRef, OkTopicStatsDTO

if TYPE_CHECKING:
    from backend.modules.jobs.interfaces import ProgressReporterProtocol


class OkApiClientProtocol(Protocol):
    """Контракт низкоуровневого клиента OK API."""

    def call(self, method: str, params: dict[str, Any]) -> Any: ...
    def get_group(self, group_ref: str) -> dict[str, Any]: ...
    def fetch_all_stat_topics(
        self,
        gid: str,
        *,
        max_topics: int | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        on_progress: "Callable[[int, int | None], None] | None" = None,
    ) -> list[dict[str, Any]]: ...
    def fetch_public_topic_ids(
        self,
        group_id: str,
        *,
        shortname: str | None = None,
        max_topics: int | None = None,
        on_progress: "Callable[[int, int | None], None] | None" = None,
    ) -> list[str]: ...
    def get_mediatopics(self, topic_ids: list[str]) -> list[dict[str, Any]]: ...
    def fetch_all_comments(self, topic_id: str, *, max_comments: int = 500) -> list[dict[str, Any]]: ...


class OkLinkParserProtocol(Protocol):
    """Контракт парсера OK-ссылок."""

    def parse(self, raw: str) -> OkLinkRef: ...


class OkIngestionServiceProtocol(Protocol):
    """Контракт сервиса импорта OK-ссылки."""

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
    ) -> OkIngestResult: ...


class OkIngestionRepositoryProtocol(Protocol):
    """Контракт репозитория OK-импорта."""

    async def get_or_create_ok_network(self) -> SocialNetwork: ...
    async def resolve_organization(self, user: User) -> Organization: ...
    async def get_or_create_public(self, org: Organization, name: str, description: str | None) -> Public: ...
    async def get_or_create_social_link(
        self,
        public: Public,
        network: SocialNetwork,
        *,
        url: str,
        external_public_id: str,
        title: str | None,
    ) -> PublicSocialLink: ...
    async def upsert_topic_with_publication(
        self,
        *,
        org: Organization,
        public: Public,
        link: PublicSocialLink,
        user: User,
        group_id: str,
        topic: dict[str, Any],
    ) -> tuple[Post, Publication]: ...
    async def upsert_post_metric(self, publication: Publication, topic: dict[str, Any], stats: OkTopicStatsDTO) -> None: ...
    async def upsert_comments(self, publication: Publication, ok_comments: Iterable[dict[str, Any]]) -> int: ...
    async def upsert_public_metric(
        self,
        link: PublicSocialLink,
        *,
        members: int,
        posts_total: int,
        sum_views: int,
        sum_likes: int,
        sum_comments: int,
        sum_reposts: int,
    ) -> None: ...
    async def add_ingest_audit_log(
        self,
        *,
        user: User,
        link: PublicSocialLink,
        public: Public,
        mode: str,
        posts_imported: int,
        comments_imported: int,
    ) -> None: ...
    async def commit(self) -> None: ...
    async def rollback(self) -> None: ...


class OkAnalyticsRefreshServiceProtocol(Protocol):
    """Контракт обновления аналитики после OK-импорта."""

    async def refresh(self, user: User) -> None: ...
