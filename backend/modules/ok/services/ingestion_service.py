"""Сервис импорта OK-ссылок без прямого SQL."""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from backend.app.config import settings
from backend.db import Organization, Public, PublicSocialLink, Publication, SocialNetwork, User
from backend.modules.jobs.interfaces import ProgressReporterProtocol
from backend.modules.ok.dto.dto import (
    OkIngestResult,
    OkLinkRef,
    OkLinkType,
    OkOwnerInfoDTO,
    OkTopicStatsDTO,
)
from backend.modules.ok.dto.topic_mapper import OkTopicMapper
from backend.modules.ok.services.owner_resolver_service import OkOwnerResolverService
from backend.modules.ok.utils.constants import (
    COMMENT_FETCH_CONCURRENCY,
    OK_ACCESS_DENIED_CODES,
    OK_STATS_UNAVAILABLE_CODES,
)
from backend.modules.ok.utils.errors import InvalidOkLinkError, OkApiError, OkIngestionError
from backend.modules.ok.utils.interfaces import (
    OkAnalyticsRefreshServiceProtocol,
    OkApiClientProtocol,
    OkIngestionRepositoryProtocol,
    OkLinkParserProtocol,
)

logger = logging.getLogger(__name__)

_PROFILE_UNSUPPORTED = (
    "OK API не отдаёт ленту профиля сторонним приложениям — импортировать можно "
    "только группы. Укажите ссылку вида ok.ru/group/<id>."
)

_STAT_TOPICS_FORBIDDEN = (
    "OK не отдал список тем: перечень возвращает только group.getStatTopics, "
    "а это статистика группы. Нужен токен администратора группы и право "
    "VALUABLE_ACCESS у приложения. Импортированы только данные группы."
)

_PUBLIC_FEED_FALLBACK_NOTE = (
    "Статистика группы недоступна (токен не администратора) — темы получены "
    "из публичной ленты. Лайки и число комментариев взяты из самих тем; "
    "просмотры и охват недоступны."
)


class OkIngestionService:
    """Оркестрирует импорт OK group/topic через интерфейсы."""

    def __init__(
        self,
        *,
        repository: OkIngestionRepositoryProtocol,
        api_client: OkApiClientProtocol,
        link_parser: OkLinkParserProtocol,
        owner_resolver: OkOwnerResolverService | None = None,
        mapper: OkTopicMapper | None = None,
        analytics_refresh_service: OkAnalyticsRefreshServiceProtocol | None = None,
    ) -> None:
        """Принимает зависимости через интерфейсы."""
        self.repository = repository
        self.api_client = api_client
        self.link_parser = link_parser
        self.owner_resolver = owner_resolver or OkOwnerResolverService(api_client)
        self.mapper = mapper or OkTopicMapper()
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
    ) -> OkIngestResult:
        """Импортирует OK-ссылку поддерживаемого типа."""

        try:
            ref = self.link_parser.parse(raw_url)
        except InvalidOkLinkError as exc:
            raise OkIngestionError(str(exc)) from exc

        if ref.type == OkLinkType.PROFILE:
            raise OkIngestionError(_PROFILE_UNSUPPORTED)

        organization = await self.repository.resolve_organization(user)
        network = await self.repository.get_or_create_ok_network()

        if ref.type == OkLinkType.GROUP:
            return await self._ingest_group(
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

        if ref.type == OkLinkType.TOPIC:
            return await self._ingest_topic(
                user=user,
                organization=organization,
                network=network,
                ref=ref,
                fetch_comments=fetch_comments,
                reporter=reporter,
            )

        raise OkIngestionError(f"Неизвестный тип OK-ссылки: {ref.type}")

    async def _ingest_group(
        self,
        *,
        user: User,
        organization: Organization,
        network: SocialNetwork,
        ref: OkLinkRef,
        max_posts: int | None,
        fetch_comments: bool,
        date_from: datetime | None,
        date_to: datetime | None,
        reporter: ProgressReporterProtocol | None,
    ) -> OkIngestResult:
        """Импортирует группу OK."""

        notes: list[str] = []
        owner = await asyncio.to_thread(self.owner_resolver.resolve_group_owner, ref)
        public, link = await self._ensure_public_link(organization, network, owner)

        if reporter is not None:
            await reporter.update(message="Загрузка тем сообщества…")

        stat_topics = await self._fetch_stat_topics(
            owner.group_id,
            max_topics=max_posts,
            date_from=date_from,
            date_to=date_to,
            reporter=reporter,
        )

        if stat_topics is None:
            # Статистика закрыта (токен не админ) — берём id тем из публичной
            # мобильной ленты, содержимое добираем через mediatopic.getByIds.
            topic_ids = await self._fetch_public_topic_ids(
                owner, max_topics=max_posts, notes=notes, reporter=reporter
            )
            stat_topics = []
        else:
            topic_ids = [str(item.get("id")) for item in stat_topics if item.get("id")]

        topics = await self._fetch_topic_contents(topic_ids, notes, reporter)
        topics = self._filter_topics_by_period(topics, date_from, date_to)
        if not topics:
            notes.append("В группе нет доступных тем за выбранный период")

        stats_by_id = {
            stat.topic_id: stat
            for stat in (self.mapper.stats(item) for item in stat_topics)
        }

        totals = await self._save_topics(
            user=user,
            organization=organization,
            public=public,
            link=link,
            group_id=owner.group_id,
            topics=topics,
            stats_by_id=stats_by_id,
            fetch_comments=fetch_comments,
            notes=notes,
            reporter=reporter,
        )

        await self.repository.upsert_public_metric(
            link,
            members=owner.members_count,
            posts_total=len(topics),
            sum_views=totals["views"],
            sum_likes=totals["likes"],
            sum_comments=totals["comments"],
            sum_reposts=totals["reposts"],
        )

        await self._log_success(user, link, public, "group", totals)
        await self.repository.commit()
        await self._refresh_analytics(user, notes)

        return OkIngestResult(
            type=OkLinkType.GROUP,
            canonical_url=owner.canonical_url,
            public_id=str(public.id),
            public_social_link_id=str(link.id),
            posts_imported=totals["publications"],
            publications_imported=totals["publications"],
            comments_imported=totals["saved_comments"],
            notes=notes or None,
        )

    async def _ingest_topic(
        self,
        *,
        user: User,
        organization: Organization,
        network: SocialNetwork,
        ref: OkLinkRef,
        fetch_comments: bool,
        reporter: ProgressReporterProtocol | None,
    ) -> OkIngestResult:
        """Импортирует одиночную тему OK."""

        if not ref.topic_id:
            raise OkIngestionError("Не удаётся извлечь идентификатор темы из ссылки")

        notes: list[str] = []
        if reporter is not None:
            await reporter.update(total=1, done=0, message="Загрузка темы…")

        try:
            topics = await asyncio.to_thread(self.api_client.get_mediatopics, [ref.topic_id])
        except OkApiError as exc:
            raise OkIngestionError(f"OK API (mediatopic.getByIds): {exc}") from exc

        if not topics:
            raise OkIngestionError(f"Тема OK '{ref.topic_id}' не найдена или недоступна")
        topic = topics[0]

        owner_ref = ref.group_ref or self._owner_group_from_topic(topic)
        if not owner_ref:
            raise OkIngestionError(
                "Не удалось определить группу темы. Используйте полную ссылку "
                "вида ok.ru/group/<id>/topic/<id>."
            )

        owner = await asyncio.to_thread(
            self.owner_resolver.resolve_group_owner,
            OkLinkRef(
                type=OkLinkType.GROUP,
                raw_url=ref.raw_url,
                canonical_url=ref.canonical_url,
                group_ref=owner_ref,
            ),
        )
        public, link = await self._ensure_public_link(organization, network, owner)

        _, publication = await self.repository.upsert_topic_with_publication(
            org=organization,
            public=public,
            link=link,
            user=user,
            group_id=owner.group_id,
            topic=topic,
        )
        await self.repository.upsert_post_metric(
            publication, topic, self._topic_summary_stats(topic)
        )

        saved_comments = 0
        if fetch_comments:
            if reporter is not None:
                await reporter.update(message="Загрузка комментариев…")
            comments = await asyncio.to_thread(
                self._fetch_comments_safe, ref.topic_id, notes
            )
            saved_comments = await self.repository.upsert_comments(publication, comments)

        await self._log_success(
            user, link, public, "single_topic",
            {"publications": 1, "saved_comments": saved_comments},
        )
        await self.repository.commit()
        await self._refresh_analytics(user, notes)

        return OkIngestResult(
            type=OkLinkType.TOPIC,
            canonical_url=self.mapper.post_url(owner.group_id, topic),
            public_id=str(public.id),
            public_social_link_id=str(link.id),
            posts_imported=1,
            publications_imported=1,
            comments_imported=saved_comments,
            notes=notes or None,
        )

    async def _fetch_stat_topics(
        self,
        group_id: str,
        *,
        max_topics: int | None,
        date_from: datetime | None,
        date_to: datetime | None,
        reporter: ProgressReporterProtocol | None,
    ) -> list[dict[str, Any]] | None:
        """Тянет темы через статистику. None — статистика недоступна токену."""

        try:
            return await asyncio.to_thread(
                self.api_client.fetch_all_stat_topics,
                group_id,
                max_topics=max_topics,
                date_from=date_from,
                date_to=date_to,
                on_progress=self._topics_progress(reporter, "Загрузка тем сообщества"),
            )
        except OkApiError as exc:
            if exc.code in OK_STATS_UNAVAILABLE_CODES:
                return None
            raise OkIngestionError(f"OK API (group.getStatTopics): {exc}") from exc

    async def _fetch_public_topic_ids(
        self,
        owner: OkOwnerInfoDTO,
        *,
        max_topics: int | None,
        notes: list[str],
        reporter: ProgressReporterProtocol | None,
    ) -> list[str]:
        """Собирает id тем из публичной ленты m.ok.ru (фолбэк без прав админа)."""

        if reporter is not None:
            await reporter.update(message="Чтение публичной ленты группы…")
        try:
            topic_ids = await asyncio.to_thread(
                self.api_client.fetch_public_topic_ids,
                owner.group_id,
                shortname=owner.shortname,
                max_topics=max_topics,
                on_progress=self._topics_progress(reporter, "Чтение публичной ленты"),
            )
        except OkApiError as exc:
            notes.append(_STAT_TOPICS_FORBIDDEN)
            notes.append(f"Публичная лента группы тоже недоступна: {exc}")
            return []

        if topic_ids:
            notes.append(_PUBLIC_FEED_FALLBACK_NOTE)
        else:
            notes.append(_STAT_TOPICS_FORBIDDEN)
        return topic_ids

    def _filter_topics_by_period(
        self,
        topics: list[dict[str, Any]],
        date_from: datetime | None,
        date_to: datetime | None,
    ) -> list[dict[str, Any]]:
        """Оставляет темы в границах периода (включительно).

        Для статистики период уже применён на стороне OK; здесь фильтр нужен
        фолбэку через публичную ленту, где границ у источника нет.
        """

        if date_from is None and date_to is None:
            return topics

        def _utc(value: datetime) -> datetime:
            return value if value.tzinfo else value.replace(tzinfo=timezone.utc)

        result: list[dict[str, Any]] = []
        for topic in topics:
            published = self.mapper.published_at(topic)
            if date_from is not None and published < _utc(date_from):
                continue
            if date_to is not None and published > _utc(date_to):
                continue
            result.append(topic)
        return result

    async def _fetch_topic_contents(
        self,
        topic_ids: list[str],
        notes: list[str],
        reporter: ProgressReporterProtocol | None,
    ) -> list[dict[str, Any]]:
        """Догружает содержимое тем по их id."""

        if not topic_ids:
            return []

        if reporter is not None:
            await reporter.update(message=f"Загрузка содержимого {len(topic_ids)} тем…")

        try:
            return await asyncio.to_thread(self.api_client.get_mediatopics, topic_ids)
        except OkApiError as exc:
            if exc.code in OK_ACCESS_DENIED_CODES:
                notes.append(f"Не удалось загрузить содержимое тем: {exc}")
                return []
            raise OkIngestionError(f"OK API (mediatopic.getByIds): {exc}") from exc

    async def _save_topics(
        self,
        *,
        user: User,
        organization: Organization,
        public: Public,
        link: PublicSocialLink,
        group_id: str,
        topics: list[dict[str, Any]],
        stats_by_id: dict[str, OkTopicStatsDTO],
        fetch_comments: bool,
        notes: list[str],
        reporter: ProgressReporterProtocol | None,
    ) -> dict[str, int]:
        """Сохраняет темы и возвращает счетчики."""

        totals = {
            "publications": 0,
            "saved_comments": 0,
            "views": 0,
            "likes": 0,
            "comments": 0,
            "reposts": 0,
        }

        total_topics = len(topics)
        if reporter is not None:
            await reporter.update(
                total=total_topics, done=0, message=f"Сохранение тем 0/{total_topics}…"
            )

        # Сохраняем темы/метрики последовательно (одна async-сессия) и собираем
        # темы, у которых надо забрать комментарии.
        pending: list[tuple[Publication, str]] = []
        for idx, topic in enumerate(topics, start=1):
            if reporter is not None:
                reporter.raise_if_cancelled()

            topic_id = self.mapper.topic_id(topic)
            stats = stats_by_id.get(topic_id) or self._topic_summary_stats(topic)

            _, publication = await self.repository.upsert_topic_with_publication(
                org=organization,
                public=public,
                link=link,
                user=user,
                group_id=group_id,
                topic=topic,
            )
            await self.repository.upsert_post_metric(publication, topic, stats)

            totals["publications"] += 1
            totals["views"] += stats.views
            totals["likes"] += stats.likes
            totals["comments"] += stats.comments
            totals["reposts"] += stats.reshares

            if fetch_comments and stats.comments > 0:
                pending.append((publication, topic_id))

            if reporter is not None and (idx % 5 == 0 or idx == total_topics):
                await reporter.update(
                    done=idx, message=f"Сохранение тем {idx}/{total_topics}…"
                )

        if not pending:
            return totals

        # Вторая фаза — комментарии. Расширяем шкалу прогресса на число тем,
        # у которых их надо забрать, чтобы бар продолжил двигаться.
        pending_total = len(pending)
        if reporter is not None:
            await reporter.update(
                total=total_topics + pending_total,
                done=total_topics,
                message=f"Загрузка комментариев: 0/{pending_total} тем…",
            )

        # Комментарии тянем параллельно (только сеть): синхронный OK-фетч уводим
        # в поток, число одновременных запросов ограничиваем семафором.
        sem = asyncio.Semaphore(
            max(1, getattr(settings, "OK_COMMENT_FETCH_CONCURRENCY", COMMENT_FETCH_CONCURRENCY))
        )
        comments_done = 0

        async def _fetch(topic_id: str) -> list[dict[str, Any]]:
            nonlocal comments_done
            async with sem:
                if reporter is not None:
                    reporter.raise_if_cancelled()
                result = await asyncio.to_thread(self._fetch_comments_safe, topic_id, notes)
            comments_done += 1
            if reporter is not None:
                await reporter.update(
                    done=total_topics + comments_done,
                    message=f"Загрузка комментариев: {comments_done}/{pending_total} тем…",
                )
            return result

        fetched = await asyncio.gather(*[_fetch(topic_id) for _, topic_id in pending])

        # Запись комментариев — последовательно (одна async-сессия).
        for (publication, _topic_id), comments in zip(pending, fetched):
            totals["saved_comments"] += await self.repository.upsert_comments(
                publication, comments
            )

        return totals

    def _fetch_comments_safe(self, topic_id: str, notes: list[str]) -> list[dict[str, Any]]:
        """Синхронный фетч комментариев одной темы (для запуска в потоке).

        Ошибку OK гасим в note и возвращаем пустой список.
        """

        try:
            return self.api_client.fetch_all_comments(topic_id, max_comments=500)
        except OkApiError as exc:
            notes.append(f"Не удалось забрать комментарии темы {topic_id}: {exc}")
            return []

    def _topic_summary_stats(self, topic: dict[str, Any]) -> OkTopicStatsDTO:
        """Собирает метрики из самого медиатопика, когда статистики группы нет."""

        like_summary = topic.get("like_summary") or {}
        discussion_summary = topic.get("discussion_summary") or {}
        reshare_summary = topic.get("reshare_summary") or {}
        return OkTopicStatsDTO(
            topic_id=self.mapper.topic_id(topic),
            likes=int(like_summary.get("count") or 0),
            comments=int(discussion_summary.get("comments_count") or 0),
            reshares=int(reshare_summary.get("count") or 0),
            views=0,
        )

    def _owner_group_from_topic(self, topic: dict[str, Any]) -> str | None:
        """Достаёт id группы из ссылки владельца медиатопика (``group:123``)."""

        for key in ("owner_ref", "author_ref"):
            ref = topic.get(key)
            if not ref:
                continue
            kind, _, value = str(ref).partition(":")
            if kind.lower() == "group" and value:
                return value
        return None

    async def _ensure_public_link(
        self,
        organization: Organization,
        network: SocialNetwork,
        owner: OkOwnerInfoDTO,
    ) -> tuple[Public, PublicSocialLink]:
        """Создает или возвращает Public и PublicSocialLink владельца."""

        public = await self.repository.get_or_create_public(
            organization, name=owner.name, description=owner.description
        )
        link = await self.repository.get_or_create_social_link(
            public,
            network,
            url=owner.canonical_url,
            external_public_id=owner.external_public_id,
            title=owner.name,
        )
        return public, link

    def _topics_progress(self, reporter: ProgressReporterProtocol | None, label: str):
        """Колбэк прогресса пагинации тем.

        Синхронный — ``fetch_all_stat_topics`` блокирующий; обновляет job через
        update_sync и пробрасывает отмену между страницами.
        """

        if reporter is None:
            return None

        def _cb(done: int, total: int | None) -> None:
            suffix = f"{done}/{total}" if total else str(done)
            reporter.update_sync(total=total, done=done, message=f"{label}: {suffix} тем…")
            reporter.raise_if_cancelled()

        return _cb

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
            logger.exception("OK analytics refresh failed")
            notes.append(f"Автоаналитика комментариев не обновилась: {exc}")
