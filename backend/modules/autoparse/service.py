"""Оркестрация автопарсера: проверка диффа и дотягивание комментариев.

Логика одной ссылки — три фазы:
  A. Дешёвый проход ingest БЕЗ комментариев (fetch_comments=False) за окно —
     освежает посты и PostMetric.comments_count (реальные счётчики сети).
  B. Дифф по нашим данным: сумма max(real - stored, 0) по постам окна. >0 —
     есть неспаршенные комментарии.
  C. Только если дифф есть — полный ingest С комментариями за то же окно.

Новые комментарии попадают в очередь классификации (CommentAnalysis pending),
дальше их разгребает и пересобирает боли существующий воркер классификации —
поэтому автопарсер аналитику сам не трогает.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID

from backend.app.config import settings as app_settings
from backend.app.runtime_settings import get_autoparse_interval_hours
from backend.app.sentry import capture
from backend.modules.autoparse.models import AutoParseRunResult, LinkAutoParseResult
from backend.modules.autoparse.repository import AutoParseRepository, DueLink

logger = logging.getLogger(__name__)


class AutoParseService:
    """Гоняет автопарсер по «созревшим» (или всем) ссылкам пабликов."""

    def __init__(self, db_factory, *, settings=app_settings) -> None:
        # db_factory — async_session_maker: каждой ссылке нужна своя сессия,
        # чтобы упавшая транзакция не роняла остальные.
        self.db_factory = db_factory
        self.settings = settings

    async def run_once(
        self,
        *,
        only_due: bool = True,
        organization_id: UUID | None = None,
        link_id: UUID | None = None,
        now: datetime | None = None,
    ) -> AutoParseRunResult:
        """Один проход. only_due=False + link_id — прицельный ручной прогон."""

        now = now or datetime.now(timezone.utc)
        window_start = now - timedelta(days=self.settings.AUTOPARSE_LOOKBACK_DAYS)

        async with self.db_factory() as session:
            # Период автопарсера админ правит в рантайме — читаем актуальное
            # значение из БД (с дефолтом из .env), а не берём копию из конфига.
            interval_hours = await get_autoparse_interval_hours(session)
            repo = AutoParseRepository(session)
            due = await repo.list_links(
                now=now,
                interval_hours=interval_hours,
                only_due=only_due,
                organization_id=organization_id,
                link_id=link_id,
            )

        result = AutoParseRunResult(
            started_at=now.isoformat(),
            finished_at=now.isoformat(),
            lookback_days=self.settings.AUTOPARSE_LOOKBACK_DAYS,
            links_total=len(due),
        )

        for link in due:
            link_result = await self._process_link(link, window_start=window_start, now=now)
            result.links.append(link_result)
            if link_result.checked:
                result.links_checked += 1
            if link_result.parsed:
                result.links_parsed += 1
            result.comments_imported += link_result.comments_imported

        result.finished_at = datetime.now(timezone.utc).isoformat()
        logger.info(
            "Autoparse pass: links=%d checked=%d parsed=%d comments=%d",
            result.links_total,
            result.links_checked,
            result.links_parsed,
            result.comments_imported,
        )
        return result

    async def _process_link(
        self, link: DueLink, *, window_start: datetime, now: datetime
    ) -> LinkAutoParseResult:
        """Обрабатывает одну ссылку в отдельной сессии."""

        res = LinkAutoParseResult(
            link_id=str(link.link_id),
            network=link.network,
            url=link.url,
            public_id=str(link.public_id),
            public_name=link.public_name,
        )

        async with self.db_factory() as session:
            repo = AutoParseRepository(session)
            user = await repo.pick_org_user(link.organization_id)
            if user is None:
                res.skipped_reason = "no_active_org_user"
                await repo.record_error(link.link_id, res.skipped_reason)
                await session.commit()
                return res

            service = self._build_ingestion_service(session, link.network)
            if service is None:
                res.skipped_reason = f"unsupported_network:{link.network}"
                await repo.record_error(link.link_id, res.skipped_reason)
                await session.commit()
                return res

            ingest_url = self._ingest_url(link)

            try:
                # Фаза A: освежаем посты и реальные счётчики без комментов.
                await service.ingest_link(
                    user,
                    ingest_url,
                    date_from=window_start,
                    date_to=now,
                    fetch_comments=False,
                    max_posts=self.settings.AUTOPARSE_MAX_POSTS,
                )

                # Фаза B: дифф по нашим данным.
                diff = await repo.window_diff(link.link_id, window_start)
                res.checked = True
                res.posts_in_window = diff.posts_in_window
                res.real_comments = diff.real_comments
                res.stored_comments_before = diff.stored_comments
                res.unparsed_estimate = diff.unparsed
                res.had_diff = diff.has_diff

                # Фаза C: парсим комментарии только при наличии диффа.
                if diff.has_diff:
                    parsed = await service.ingest_link(
                        user,
                        ingest_url,
                        date_from=window_start,
                        date_to=now,
                        fetch_comments=True,
                        max_posts=self.settings.AUTOPARSE_MAX_POSTS,
                    )
                    res.parsed = True
                    res.comments_imported = parsed.comments_imported

                await repo.mark_checked(link.link_id, now)
                await session.commit()

            except Exception as exc:  # noqa: BLE001
                await session.rollback()
                res.error = f"{type(exc).__name__}: {exc}"
                # Не помечаем last_autoparse_at: ссылка останется «созревшей» и
                # будет повторена на следующем пробуждении воркера. Но текст
                # ошибки сохраняем — он виден в «состоянии данных по площадкам».
                error_changed = True
                try:
                    error_changed = await repo.record_error(link.link_id, res.error)
                    await session.commit()
                except Exception:  # noqa: BLE001
                    await session.rollback()
                # В трекер уходит только смена состояния. Повтор той же ошибки
                # остаётся в логе и в «состоянии данных по площадкам», иначе
                # одна нечинёная ссылка забивает трекер по событию в час.
                if error_changed:
                    capture(exc, autoparse_link_id=str(link.link_id), network=link.network)
                    logger.exception(
                        "Autoparse failed for link %s (%s)", link.link_id, link.network
                    )
                else:
                    logger.warning(
                        "Autoparse still failing for link %s (%s): %s",
                        link.link_id,
                        link.network,
                        res.error,
                    )

        return res

    def _ingest_url(self, link: DueLink) -> str:
        """URL для ingest. У OK-ссылок в БД часто лежит shortname-URL
        (ok.ru/group/<shortname>), а резолвер OK принимает только числовой UID —
        поэтому для OK при наличии числового external_public_id собираем
        каноничный числовой URL. VK-резолвер screen name понимает сам.
        """

        if link.network == "ok" and (link.external_public_id or "").isdigit():
            return f"https://ok.ru/group/{link.external_public_id}"
        return link.url

    def _build_ingestion_service(self, session, network: str):
        """Собирает ingest-сервис нужной сети на переданной сессии."""

        if network == "telegram":
            from backend.modules.telegram.services.ingestion_service import (
                TelegramIngestionService,
            )

            return TelegramIngestionService(session)

        if network == "vk":
            from backend.modules.vk.links.link_parser import VkLinkParser
            from backend.modules.vk.repositories.ingestion_repository import (
                VkIngestionRepository,
            )
            from backend.modules.vk.services.ingestion_service import VkIngestionService
            from backend.modules.vk.services.owner_resolver_service import (
                VkOwnerResolverService,
            )
            from backend.modules.vk.utils.api_client import VkApiClient

            api_client = VkApiClient()
            return VkIngestionService(
                repository=VkIngestionRepository(session),
                api_client=api_client,
                link_parser=VkLinkParser(),
                owner_resolver=VkOwnerResolverService(api_client),
            )

        if network == "ok":
            from backend.modules.ok.links.link_parser import OkLinkParser
            from backend.modules.ok.repositories.ingestion_repository import (
                OkIngestionRepository,
            )
            from backend.modules.ok.services.ingestion_service import OkIngestionService
            from backend.modules.ok.services.owner_resolver_service import (
                OkOwnerResolverService,
            )
            from backend.modules.ok.utils.api_client import OkApiClient

            api_client = OkApiClient()
            return OkIngestionService(
                repository=OkIngestionRepository(session),
                api_client=api_client,
                link_parser=OkLinkParser(),
                owner_resolver=OkOwnerResolverService(api_client),
            )

        return None
