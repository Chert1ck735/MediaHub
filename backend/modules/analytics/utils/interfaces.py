import uuid
from datetime import datetime
from typing import Protocol, Any

from backend.db import User, Pain, Comment, CommentAnalysis, Public, Publication, AnalysisSnapshot
from backend.modules.analytics.utils.public_link_filter import PublicSocialLinkFilter


class SnapshotRepositoryProtocol(Protocol):
    """Контракт репозитория аналитических snapshot'ов."""

    async def get_latest(self, user: User) -> AnalysisSnapshot | None: ...
    async def get_latest_vk(self, user: User) -> AnalysisSnapshot | None: ...
    async def list_pains(self, snapshot_id: str) -> list[Pain]: ...
    async def count_pains(self, snapshot_id: str) -> int: ...
    async def count_filtered_pains(
        self,
        snapshot_id: str,
        link_id: PublicSocialLinkFilter,
        *,
        since: datetime | None = None,
    ) -> int: ...
    async def list_vk_snapshots(self, user: User) -> list[AnalysisSnapshot]: ...
    async def list_pain_ids_for_snapshots(self, snapshot_ids: list[uuid.UUID]) -> list[uuid.UUID]: ...


class PainRepositoryProtocol(Protocol):
    """Контракт репозитория болей."""

    async def get_by_id(self, pain_id: str, user: User) -> Pain | None: ...
    async def get_evidence_urls(self, pain_id: str) -> list[str]: ...
    async def get_comment_examples(
        self,
        pain_id: str,
        *,
        link_id: PublicSocialLinkFilter = None,
    ) -> list[dict[str, Any]]: ...
    async def get_strategy_ids(self, pain_id: str) -> list[str]: ...
    async def get_strategy_descriptions(self, pain_id: str) -> list[str]: ...
    # Пакетные варианты для списка болей.
    async def get_evidence_urls_map(self, pain_ids: list[str]) -> dict[str, list[str]]: ...
    async def get_strategies_map(
        self, pain_ids: list[str]
    ) -> dict[str, list[tuple[str, str]]]: ...


class PublicationRepositoryProtocol(Protocol):
    """Контракт репозитория публикаций и площадок."""

    async def list_vk_public_names(self, user: User) -> list[str]: ...
    async def get_public_by_id(self, public_id: str, user: User) -> Public | None: ...
    async def list_publications_for_public(self, public_id: uuid.UUID) -> list[Publication]: ...


class CommentRepositoryProtocol(Protocol):
    """Контракт репозитория комментариев."""

    async def get_existing_analysis(self, comment_id: uuid.UUID) -> CommentAnalysis | None: ...
    async def list_comments_for_publication(
        self,
        publication_id: uuid.UUID,
        *,
        since: datetime | None = None,
    ) -> list[Comment]: ...


class PublicQueryRepositoryProtocol(Protocol):
    """Контракт read-репозитория публичной analytics-страницы."""

    async def list_publics(self, user: User) -> list[dict[str, Any]]: ...
    async def list_publications(
        self,
        user: User,
        *,
        public_social_link_id: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]: ...
    async def list_recent_comments(
        self,
        user: User,
        *,
        publication_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]: ...


class EventRepositoryProtocol(Protocol):
    """Контракт репозитория событий analytics."""

    async def list_upcoming_events_by_pain(
        self,
        pain_ids: list[uuid.UUID],
        *,
        days_ahead: int,
    ) -> dict[str, list[dict[str, Any]]]: ...


class SnapshotSignalsServiceProtocol(Protocol):
    """Контракт сервиса агрегатов snapshot'а."""

    async def get_counts(
        self,
        snapshot_id: str,
        user: User,
        *,
        since: datetime | None = None,
        link_id: PublicSocialLinkFilter = None,
    ) -> dict[str, Any]: ...


class VkSnapshotPurgeServiceProtocol(Protocol):
    """Контракт очистки VK snapshot'ов."""

    async def purge_all_snapshots(self, user: User) -> list[uuid.UUID]: ...

    async def delete_orphan_pains(
        self,
        snapshot_id: uuid.UUID,
        previous_pain_ids: list[uuid.UUID],
    ) -> None: ...


class VkSnapshotBuilderProtocol(Protocol):
    """Контракт сборки VK snapshot'а: сначала classify (LLM, без транзакции),
    потом build (persist в короткой write-транзакции)."""

    async def classify(
        self,
        user: User,
        *,
        force_reclassify: bool = False,
        progress=None,
    ) -> Any: ...

    async def build(
        self,
        user: User,
        *,
        force_reclassify: bool = False,
        progress=None,
        classification: Any | None = None,
    ) -> tuple[AnalysisSnapshot, dict[str, int]]: ...
