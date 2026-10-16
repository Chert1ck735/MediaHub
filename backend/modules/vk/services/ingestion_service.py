"""Сервис импорта VK-ссылок без прямого SQL."""

import asyncio
import logging
from datetime import datetime
from typing import Any

from backend.app.config import settings
from backend.db import User, PublicSocialLink, Public, Organization, SocialNetwork, Publication
from backend.modules.vk.dto.dto import IngestResult, VkLinkRef, VkLinkType, VkOwnerInfoDTO
from backend.modules.vk.services.owner_resolver_service import VkOwnerResolverService
from backend.modules.vk.utils.constants import COMMENT_FETCH_CONCURRENCY, PRIVATE_CODES
from backend.modules.vk.utils.errors import IngestionError, InvalidVkLinkError, VkApiError
from backend.modules.jobs.interfaces import ProgressReporterProtocol
from backend.modules.vk.utils.interfaces import (
    VkApiClientProtocol,
    VkIngestionRepositoryProtocol,
    VkLinkParserProtocol,
    VkAnalyticsRefreshServiceProtocol,
)

logger = logging.getLogger(__name__)


class VkIngestionService:
    """Оркестрирует импорт VK community/profile/post через интерфейсы."""

    def __init__(
        self,
        *,
        repository: VkIngestionRepositoryProtocol,
        api_client: VkApiClientProtocol,
        link_parser: VkLinkParserProtocol,
        owner_resolver: VkOwnerResolverService | None = None,
        analytics_refresh_service: VkAnalyticsRefreshServiceProtocol | None = None,
    ) -> None:
        """Принимает зависимости через интерфейсы."""
        self.repository = repository
        self.api_client = api_client
        self.link_parser = link_parser
        self.owner_resolver = owner_resolver or VkOwnerResolverService(api_client)
        self.analytics_refresh_service = analytics_refresh_service

    async def ingest_link(
        self,
        user: User,
        raw_url: str,
        *,
        max_posts: int | None = None,
        fetch_comments: bool = True,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        reporter: ProgressReporterProtocol | None = None,
    ) -> IngestResult:
        """Импортирует VK-ссылку любого поддерживаемого типа."""
        try:
            ref = self.link_parser.parse(raw_url)
        except InvalidVkLinkError as exc:
            raise IngestionError(str(exc)) from exc

        organization = await self.repository.resolve_organization(user)
        network = await self.repository.get_or_create_vk_network()

        if ref.type == VkLinkType.COMMUNITY and ref.domain and ref.owner_id is None:
            ref = await asyncio.to_thread(self.owner_resolver.resolve_screen_name, ref)

        if ref.type == VkLinkType.COMMUNITY:
            return await self._ingest_community(
                user=user,
                organization=organization,
                network=network,
                ref=ref,
                max_posts=max_posts,
                fetch_comments=fetch_comments,
                date_from=date_from,
                date_to=date_to,
                reporter=reporter,
            )

        if ref.type == VkLinkType.PROFILE:
            return await self._ingest_profile(
                user=user,
                organization=organization,
                network=network,
                ref=ref,
                max_posts=max_posts,
                fetch_comments=fetch_comments,
                date_from=date_from,
                date_to=date_to,
                reporter=reporter,
            )

        if ref.type == VkLinkType.POST:
            return await self._ingest_post(
                user=user,
                organization=organization,
                network=network,
                ref=ref,
                fetch_comments=fetch_comments,
                reporter=reporter,
            )

        raise IngestionError(f"Неизвестный тип VK-ссылки: {ref.type}")

    async def _ingest_community(
        self,
        *,
        user: User,
        organization: Organization,
        network: SocialNetwork,
        ref: VkLinkRef,
        max_posts: int | None,
        fetch_comments: bool,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        reporter: ProgressReporterProtocol | None = None,
    ) -> IngestResult:
        """Импортирует сообщество VK."""
        notes: list[str] = []
        owner = await asyncio.to_thread(self.owner_resolver.resolve_community_owner, ref)
        public, link = await self._ensure_public_link(organization, network, owner)

        if reporter is not None:
            await reporter.update(message="Загрузка стены сообщества…")
        try:
            posts = await asyncio.to_thread(
                self.api_client.fetch_all_wall,
                owner_id=owner.owner_id,
                max_posts=max_posts,
                date_from=date_from,
                date_to=date_to,
                on_progress=self._wall_progress(reporter, "Загрузка стены сообщества"),
            )
        except VkApiError as exc:
            raise IngestionError(f"VK API (wall.get): {exc}") from exc

        if not posts:
            notes.append("Стена пустая или закрыта")

        stats = await self._save_posts(
            user=user,
            organization=organization,
            public=public,
            link=link,
            posts=posts,
            owner_id=owner.owner_id,
            fetch_comments=fetch_comments,
            notes=notes,
            reporter=reporter,
        )

        await self.repository.upsert_public_metric(
            link,
            members=owner.members_count,
            posts_total=len(posts),
            sum_views=stats["views"],
            sum_likes=stats["likes"],
            sum_comments=stats["comments"],
            sum_reposts=stats["reposts"],
        )

        await self._log_success(user, link, public, "community", stats)
        await self.repository.commit()
        await self._refresh_analytics(user, notes)

        return IngestResult(
            type=VkLinkType.COMMUNITY,
            canonical_url=owner.canonical_url,
            public_id=str(public.id),
            public_social_link_id=str(link.id),
            posts_imported=stats["publications"],
            publications_imported=stats["publications"],
            comments_imported=stats["saved_comments"],
            notes=notes or None,
        )

    async def _ingest_profile(
        self,
        *,
        user: User,
        organization: Organization,
        network: SocialNetwork,
        ref: VkLinkRef,
        max_posts: int | None,
        fetch_comments: bool,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        reporter: ProgressReporterProtocol | None = None,
    ) -> IngestResult:
        """Импортирует профиль VK."""
        notes: list[str] = []
        owner = await asyncio.to_thread(self.owner_resolver.resolve_profile_owner, ref)
        public, link = await self._ensure_public_link(organization, network, owner)

        if owner.is_closed and not owner.can_access_closed:
            notes.append("Профиль закрыт. Стена и комментарии не импортируются.")
            await self.repository.upsert_public_metric(
                link,
                members=owner.members_count,
                posts_total=0,
                sum_views=0,
                sum_likes=0,
                sum_comments=0,
                sum_reposts=0,
            )
            await self._log_success(
                user,
                link,
                public,
                "profile",
                {"publications": 0, "saved_comments": 0},
            )
            await self.repository.commit()
            await self._refresh_analytics(user, notes)
            return self._empty_profile_result(owner, public, link, notes)

        if reporter is not None:
            await reporter.update(message="Загрузка стены профиля…")
        try:
            posts = await asyncio.to_thread(
                self.api_client.fetch_all_wall,
                owner_id=owner.owner_id,
                max_posts=max_posts,
                date_from=date_from,
                date_to=date_to,
                on_progress=self._wall_progress(reporter, "Загрузка стены профиля"),
            )
        except VkApiError as exc:
            if exc.code in PRIVATE_CODES:
                notes.append(
                    "Стена профиля недоступна по правам токена. "
                    "Импортированы только базовые данные профиля."
                )
                await self.repository.upsert_public_metric(
                    link,
                    members=owner.members_count,
                    posts_total=0,
                    sum_views=0,
                    sum_likes=0,
                    sum_comments=0,
                    sum_reposts=0,
                )
                await self._log_success(
                    user,
                    link,
                    public,
                    "profile",
                    {"publications": 0, "saved_comments": 0},
                )
                await self.repository.commit()
                await self._refresh_analytics(user, notes)
                return self._empty_profile_result(owner, public, link, notes)

            raise IngestionError(f"VK API (wall.get): {exc}") from exc

        stats = await self._save_posts(
            user=user,
            organization=organization,
            public=public,
            link=link,
            posts=posts,
            owner_id=owner.owner_id,
            fetch_comments=fetch_comments,
            notes=notes,
            reporter=reporter,
        )

        await self.repository.upsert_public_metric(
            link,
            members=owner.members_count,
            posts_total=len(posts),
            sum_views=stats["views"],
            sum_likes=stats["likes"],
            sum_comments=stats["comments"],
            sum_reposts=stats["reposts"],
        )

        await self._log_success(user, link, public, "profile", stats)
        await self.repository.commit()
        await self._refresh_analytics(user, notes)

        return IngestResult(
            type=VkLinkType.PROFILE,
            canonical_url=owner.canonical_url,
            public_id=str(public.id),
            public_social_link_id=str(link.id),
            posts_imported=stats["publications"],
            publications_imported=stats["publications"],
            comments_imported=stats["saved_comments"],
            notes=notes or None,
        )

    async def _ingest_post(
        self,
        *,
        user: User,
        organization: Organization,
        network: SocialNetwork,
        ref: VkLinkRef,
        fetch_comments: bool,
        reporter: ProgressReporterProtocol | None = None,
    ) -> IngestResult:
        """Импортирует одиночный пост VK."""
        if ref.owner_id is None or ref.post_id is None:
            raise IngestionError("Не удаётся извлечь owner_id/post_id из ссылки")

        notes: list[str] = []
        owner = await asyncio.to_thread(self.owner_resolver.resolve_post_owner, ref)
        public, link = await self._ensure_public_link(organization, network, owner)

        if reporter is not None:
            await reporter.update(total=1, done=0, message="Загрузка поста…")
        try:
            vk_post = await asyncio.to_thread(self.api_client.wall_get_by_id, ref.owner_id, ref.post_id)
        except VkApiError as exc:
            raise IngestionError(f"VK API (wall.getById): {exc}") from exc

        _, publication = await self.repository.upsert_post_with_publication(
            org=organization,
            public=public,
            link=link,
            user=user,
            vk_post=vk_post,
        )
        await self.repository.upsert_post_metric(publication, vk_post)

        saved_comments = 0
        if fetch_comments:
            if reporter is not None:
                await reporter.update(message="Загрузка комментариев…")
            saved_comments = await self._load_and_save_comments(
                publication=publication,
                owner_id=ref.owner_id,
                post_id=ref.post_id,
                notes=notes,
            )

        await self._log_success(
            user,
            link,
            public,
            "single_post",
            {"publications": 1, "saved_comments": saved_comments},
        )
        await self.repository.commit()
        await self._refresh_analytics(user, notes)

        return IngestResult(
            type=VkLinkType.POST,
            canonical_url=ref.canonical_url,
            public_id=str(public.id),
            public_social_link_id=str(link.id),
            posts_imported=1,
            publications_imported=1,
            comments_imported=saved_comments,
            notes=notes or None,
        )

    async def _ensure_public_link(
        self,
        organization: Organization,
        network: SocialNetwork,
        owner: VkOwnerInfoDTO,
    ) -> tuple[Public, PublicSocialLink]:
        """Создает или возвращает Public и PublicSocialLink владельца."""
        public = await self.repository.get_or_create_public(
            organization,
            name=owner.name,
            description=owner.description,
        )
        link = await self.repository.get_or_create_social_link(
            public,
            network,
            url=owner.canonical_url,
            external_public_id=owner.external_public_id,
            title=owner.name,
        )
        return public, link

    def _wall_progress(
        self,
        reporter: ProgressReporterProtocol | None,
        label: str,
    ):
        """Колбэк прогресса пагинации стены.

        Синхронный — ``fetch_all_wall`` блокирующий; обновляет job через
        update_sync и пробрасывает отмену между страницами.
        """
        if reporter is None:
            return None

        def _cb(done: int, total: int | None) -> None:
            suffix = f"{done}/{total}" if total else str(done)
            reporter.update_sync(total=total, done=done, message=f"{label}: {suffix} постов…")
            reporter.raise_if_cancelled()

        return _cb

    async def _save_posts(
        self,
        *,
        user: User,
        organization: Organization,
        public: Public,
        link: PublicSocialLink,
        posts: list[dict[str, Any]],
        owner_id: int,
        fetch_comments: bool,
        notes: list[str],
        reporter: ProgressReporterProtocol | None = None,
    ) -> dict[str, int]:
        """Сохраняет список постов и возвращает счетчики."""
        stats = {
            "publications": 0,
            "saved_comments": 0,
            "views": 0,
            "likes": 0,
            "comments": 0,
            "reposts": 0,
        }

        total_posts = len(posts)
        if reporter is not None:
            await reporter.update(
                total=total_posts, done=0,
                message=f"Сохранение постов 0/{total_posts}…",
            )

        # Сохраняем посты/метрики последовательно (одна async-сессия) и собираем
        # посты, у которых надо забрать комментарии.
        pending: list[tuple[Publication, int]] = []
        for idx, vk_post in enumerate(posts, start=1):
            if reporter is not None:
                reporter.raise_if_cancelled()
            _, publication = await self.repository.upsert_post_with_publication(
                org=organization,
                public=public,
                link=link,
                user=user,
                vk_post=vk_post,
            )
            await self.repository.upsert_post_metric(publication, vk_post)

            stats["publications"] += 1
            stats["views"] += (vk_post.get("views") or {}).get("count", 0)
            stats["likes"] += (vk_post.get("likes") or {}).get("count", 0)
            stats["comments"] += (vk_post.get("comments") or {}).get("count", 0)
            stats["reposts"] += (vk_post.get("reposts") or {}).get("count", 0)

            if fetch_comments and (vk_post.get("comments") or {}).get("count", 0) > 0:
                pending.append((publication, int(vk_post["id"])))

            if reporter is not None and (idx % 5 == 0 or idx == total_posts):
                await reporter.update(
                    done=idx, message=f"Сохранение постов {idx}/{total_posts}…",
                )

        if not pending:
            return stats

        # Вторая фаза — комментарии. Расширяем шкалу прогресса на число постов,
        # у которых их надо забрать, чтобы бар продолжил двигаться, а не замер.
        pending_total = len(pending)
        if reporter is not None:
            await reporter.update(
                total=total_posts + pending_total, done=total_posts,
                message=f"Загрузка комментариев: 0/{pending_total} постов…",
            )

        # Комментарии тянем параллельно (только сеть): синхронный VK-фетч уводим
        # в поток, число одновременных запросов ограничиваем семафором.
        sem = asyncio.Semaphore(
            max(1, getattr(settings, "VK_COMMENT_FETCH_CONCURRENCY", COMMENT_FETCH_CONCURRENCY))
        )
        comments_done = 0

        async def _fetch(post_id: int) -> list[dict[str, Any]]:
            nonlocal comments_done
            async with sem:
                if reporter is not None:
                    reporter.raise_if_cancelled()
                result = await asyncio.to_thread(
                    self._fetch_comments_safe, owner_id, post_id, notes
                )
            comments_done += 1
            if reporter is not None:
                await reporter.update(
                    done=total_posts + comments_done,
                    message=f"Загрузка комментариев: {comments_done}/{pending_total} постов…",
                )
            return result

        fetched = await asyncio.gather(*[_fetch(post_id) for _, post_id in pending])

        # Запись комментариев — последовательно (одна async-сессия).
        for (publication, _post_id), comments in zip(pending, fetched):
            stats["saved_comments"] += await self.repository.upsert_comments(
                publication, comments
            )

        return stats

    def _fetch_comments_safe(
        self,
        owner_id: int,
        post_id: int,
        notes: list[str],
    ) -> list[dict[str, Any]]:
        """Синхронный фетч комментариев одного поста (для запуска в потоке).

        Ошибку VK гасим в note и возвращаем пустой список — поведение как у
        прежнего последовательного пути.
        """
        try:
            return self.api_client.fetch_all_comments(
                owner_id=owner_id,
                post_id=post_id,
                max_comments=settings.VK_COMMENTS_MAX_PER_POST or None,
            )
        except VkApiError as exc:
            notes.append(f"Не удалось забрать комментарии поста {post_id}: {exc}")
            return []

    async def _load_and_save_comments(
        self,
        *,
        publication: Publication,
        owner_id: int,
        post_id: int,
        notes: list[str],
    ) -> int:
        """Загружает и сохраняет комментарии одного поста."""
        try:
            comments = self.api_client.fetch_all_comments(
                owner_id=owner_id,
                post_id=post_id,
                max_comments=settings.VK_COMMENTS_MAX_PER_POST or None,
            )
        except VkApiError as exc:
            notes.append(f"Не удалось забрать комментарии поста {post_id}: {exc}")
            comments = []

        return await self.repository.upsert_comments(publication, comments)

    async def _log_success(
        self,
        user: User,
        link: PublicSocialLink,
        public: Public,
        mode: str,
        stats: dict[str, int],
    ) -> None:
        """Пишет audit-log успешного импорта через репозиторий."""
        await self.repository.add_ingest_audit_log(
            user=user,
            link=link,
            public=public,
            mode=mode,
            posts_imported=stats.get("publications", 0),
            comments_imported=stats.get("saved_comments", 0),
        )

    async def _refresh_analytics(self, user: User, notes: list[str]) -> None:
        """Обновляет аналитический snapshot через отдельный сервис."""
        if self.analytics_refresh_service is None:
            return

        try:
            await self.analytics_refresh_service.refresh(user)
        except Exception as exc:  # noqa: BLE001
            await self.repository.rollback()
            logger.exception("VK analytics refresh failed")
            notes.append(f"Автоаналитика комментариев не обновилась: {exc}")

    def _empty_profile_result(
        self,
        owner: VkOwnerInfoDTO,
        public: Public,
        link: PublicSocialLink,
        notes: list[str],
    ) -> IngestResult:
        """Возвращает результат профиля без постов."""
        return IngestResult(
            type=VkLinkType.PROFILE,
            canonical_url=owner.canonical_url,
            public_id=str(public.id),
            public_social_link_id=str(link.id),
            posts_imported=0,
            publications_imported=0,
            comments_imported=0,
            notes=notes,
        )
