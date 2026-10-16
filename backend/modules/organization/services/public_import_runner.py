"""Применение подтверждённых строк импорта площадок.

Каждая строка проходит штатный ingest — тот же, что и ручное добавление ссылки
в панели. Это принципиально: ingest резолвит настоящее имя площадки и
``external_public_id``, а без них автопарсер при первом же проходе создал бы
рядом вторую площадку, а импортированная осталась бы пустой.

Работает внутри фоновой задачи: строк может быть много, каждая — это поход в
API соцсети.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Iterable, Sequence

from backend.db.users import User
from backend.db.database import async_session_maker
from backend.modules.jobs.models import JobCancelled
from backend.modules.jobs.store import ProgressReporter
from backend.modules.organization.schemas import (
    PublicImportResultResponse,
    PublicImportRowPreview,
)
from backend.modules.organization.services.audit_service import AuditService
from backend.modules.organization.services.public_import_service import (
    social_network_code,
)


class _CancelOnlyReporter:
    """Пробрасывает в ingest только отмену.

    Свой прогресс ingest считает в постах, а мы — в площадках, поэтому его
    ``update`` игнорируем: иначе счётчик строк и полоска скачут.
    """

    def __init__(self, reporter: ProgressReporter) -> None:
        self._reporter = reporter

    async def update(self, **_kwargs) -> None:
        return None

    async def inc(self, **_kwargs) -> None:
        return None

    def update_sync(self, **_kwargs) -> None:
        return None

    def is_cancelled(self) -> bool:
        return self._reporter.is_cancelled()

    def raise_if_cancelled(self) -> None:
        self._reporter.raise_if_cancelled()


async def _ingest_one(
    session,
    user: User,
    url: str,
    network: str,
    *,
    date_from: datetime | None,
    date_to: datetime | None,
    reporter: ProgressReporter | None,
) -> None:
    """Импортирует одну площадку через сервис нужной соцсети."""
    if network == "telegram":
        from backend.modules.telegram.services.ingestion_service import TelegramIngestionService

        service = TelegramIngestionService(session)
    elif network == "ok":
        from backend.modules.ok.repositories.ingestion_repository import (
            OkIngestionRepository,
        )
        from backend.modules.ok.services.ingestion_service import OkIngestionService
        from backend.modules.ok.services.owner_resolver_service import (
            OkOwnerResolverService,
        )
        from backend.modules.ok.utils.api_client import OkApiClient
        from backend.modules.ok.links.link_parser import OkLinkParser

        api_client = OkApiClient()
        service = OkIngestionService(
            repository=OkIngestionRepository(session),
            api_client=api_client,
            link_parser=OkLinkParser(),
            owner_resolver=OkOwnerResolverService(api_client),
        )
    else:
        from backend.modules.vk.repositories.ingestion_repository import (
            VkIngestionRepository,
        )
        from backend.modules.vk.services.ingestion_service import VkIngestionService
        from backend.modules.vk.services.owner_resolver_service import (
            VkOwnerResolverService,
        )
        from backend.modules.vk.utils.api_client import VkApiClient
        from backend.modules.vk.links.link_parser import VkLinkParser

        api_client = VkApiClient()
        service = VkIngestionService(
            repository=VkIngestionRepository(session),
            api_client=api_client,
            link_parser=VkLinkParser(),
            owner_resolver=VkOwnerResolverService(api_client),
        )

    await service.ingest_link(
        user,
        url,
        fetch_comments=True,
        date_from=date_from,
        date_to=date_to,
        reporter=_CancelOnlyReporter(reporter) if reporter is not None else None,
    )


async def run_public_import(
    *,
    user: User,
    organization_id: uuid.UUID,
    rows: Sequence[PublicImportRowPreview],
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    reporter: ProgressReporter | None = None,
) -> PublicImportResultResponse:
    """Создаёт площадки по строкам превью и возвращает сводку."""
    to_create = [r for r in rows if r.status == "create" and r.url]
    created = 0
    skipped = sum(1 for r in rows if r.status == "skip")
    error_rows: list[PublicImportRowPreview] = [
        r for r in rows if r.status == "error" or (r.status == "create" and not r.url)
    ]

    if reporter is not None:
        await reporter.update(
            message="Импорт площадок…", done=0, total=len(to_create)
        )

    for index, row in enumerate(to_create, start=1):
        if reporter is not None:
            reporter.raise_if_cancelled()

        url = (row.url or "").strip()
        network = social_network_code(url) or "vk"
        try:
            async with async_session_maker() as session:
                await _ingest_one(
                    session,
                    user,
                    url,
                    network,
                    date_from=date_from,
                    date_to=date_to,
                    reporter=reporter,
                )
            created += 1
        except JobCancelled:
            # Отмена — не ошибка строки: пробрасываем, чтобы задача встала в
            # статус cancelled, а уже созданные площадки остались в БД.
            raise
        except Exception as exc:  # noqa: BLE001 — одна строка не должна ронять импорт
            error_rows.append(
                row.model_copy(
                    update={"status": "error", "errors": [f"Ошибка импорта: {exc}"]}
                )
            )

        if reporter is not None:
            # Показываем обработанные, а не созданные: иначе на файле, где
            # строки падают, счётчик стоит на нуле и выглядит как зависший.
            await reporter.update(
                message=f"Обработано {index} из {len(to_create)}, создано {created}",
                done=index,
                total=len(to_create),
            )

    async with async_session_maker() as session:
        AuditService(session).record(
            organization_id=organization_id,
            actor_user_id=user.id,
            entity_type="public_import",
            action="import",
            after={
                "created": created,
                "skipped": skipped,
                "errors": len(error_rows),
            },
        )
        await session.commit()

    return PublicImportResultResponse(
        created=created,
        skipped=skipped,
        errors=len(error_rows),
        error_rows=error_rows,
    )


def revalidate(
    rows: Iterable[PublicImportRowPreview],
) -> list[PublicImportRowPreview]:
    """Отбрасывает статусы, которые клиент мог подменить.

    Превью считает сервер, но подтверждение приходит с клиента, поэтому строки
    без корректной ссылки на поддерживаемую соцсеть переводим в ошибку.
    """
    checked: list[PublicImportRowPreview] = []
    for row in rows:
        if row.status == "create" and (
            not row.url or social_network_code(row.url) is None
        ):
            checked.append(
                row.model_copy(
                    update={
                        "status": "error",
                        "errors": ["Ссылка не прошла проверку на сервере"],
                    }
                )
            )
        else:
            checked.append(row)
    return checked
