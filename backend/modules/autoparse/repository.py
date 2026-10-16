"""Репозиторий автопарсера: выбор ссылок к проверке и дифф по нашим данным."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.comments import Comment
from backend.db.enums import UserStatus
from backend.db.organizations import Organization
from backend.db.post_metrics import PostMetric
from backend.db.public_social_links import PublicSocialLink
from backend.db.publications import Publication
from backend.db.publics import Public
from backend.db.social_networks import SocialNetwork
from backend.db.users import User

# Сети, которые умеет парсить автопарсер (есть ingest-сервис + дешёвый счётчик
# комментов у стены/тем).
SUPPORTED_NETWORKS = ("vk", "ok", "telegram")


@dataclass
class DueLink:
    """Ссылка паблика, которую автопарсер должен проверить."""

    link_id: UUID
    network: str
    url: str
    external_public_id: str | None
    public_id: UUID
    public_name: str
    organization_id: UUID
    last_autoparse_at: datetime | None


@dataclass
class WindowDiff:
    """Сравнение «наши данные vs реальность» за окно по одной ссылке."""

    posts_in_window: int
    real_comments: int
    stored_comments: int
    unparsed: int  # sum(max(real - stored, 0)) по постам окна

    @property
    def has_diff(self) -> bool:
        return self.unparsed > 0


class AutoParseRepository:
    """SQL автопарсера: без сети и бизнес-логики."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list_links(
        self,
        *,
        now: datetime,
        interval_hours: int,
        only_due: bool,
        organization_id: UUID | None = None,
        link_id: UUID | None = None,
    ) -> list[DueLink]:
        """Активные ссылки поддержанных сетей, включённые в автопарсер.

        only_due=True оставляет лишь «созревшие»: ни разу не проверялись или
        проверялись раньше, чем interval_hours назад. only_due=False возвращает
        все (для ручного прогона).
        """

        q = (
            select(
                PublicSocialLink.id,
                SocialNetwork.code,
                PublicSocialLink.url,
                PublicSocialLink.external_public_id,
                Public.id,
                Public.name,
                Public.organization_id,
                PublicSocialLink.last_autoparse_at,
            )
            .select_from(PublicSocialLink)
            .join(SocialNetwork, SocialNetwork.id == PublicSocialLink.social_network_id)
            .join(Public, Public.id == PublicSocialLink.public_id)
            .join(Organization, Organization.id == Public.organization_id)
            .where(PublicSocialLink.is_active.is_(True))
            .where(PublicSocialLink.autoparse_enabled.is_(True))
            .where(Public.is_active.is_(True))
            .where(Organization.is_active.is_(True))
            .where(SocialNetwork.code.in_(SUPPORTED_NETWORKS))
        )

        if organization_id is not None:
            q = q.where(Public.organization_id == organization_id)
        if link_id is not None:
            q = q.where(PublicSocialLink.id == link_id)
        if only_due:
            cutoff = now - timedelta(hours=interval_hours)
            q = q.where(
                (PublicSocialLink.last_autoparse_at.is_(None))
                | (PublicSocialLink.last_autoparse_at < cutoff)
            )

        q = q.order_by(PublicSocialLink.last_autoparse_at.asc().nulls_first())

        rows = (await self.db.execute(q)).all()
        return [
            DueLink(
                link_id=row[0],
                network=row[1],
                url=row[2],
                external_public_id=row[3],
                public_id=row[4],
                public_name=row[5],
                organization_id=row[6],
                last_autoparse_at=row[7],
            )
            for row in rows
        ]

    async def pick_org_user(self, organization_id: UUID) -> User | None:
        """Активный пользователь организации — от его имени идёт ingest.

        Нужен, потому что ingest-сервис резолвит организацию по user и
        проставляет author_id постам. superadmin/admin приоритетнее.
        """

        q = (
            select(User)
            .where(User.organization_id == organization_id)
            .where(User.status == UserStatus.active)
            .order_by(User.role.asc(), User.created_at.asc())
            .limit(1)
        )
        return (await self.db.execute(q)).scalar_one_or_none()

    async def window_diff(self, link_id: UUID, window_start: datetime) -> WindowDiff:
        """Считает по окну: постов, реальных комментов (по метрикам), наших и
        сколько не хватает.

        «Реальный» счётчик берём из PostMetric.comments_count — его освежает
        проход ingest без комментариев (fetch_comments=False). «Наши» — живые
        строки comments. Разницу max(real-stored,0) суммируем: положительная
        сумма = есть неспаршенные комментарии.
        """

        metrics_sub = (
            select(
                PostMetric.publication_id.label("pub_id"),
                func.max(PostMetric.comments_count).label("real"),
            )
            .group_by(PostMetric.publication_id)
            .subquery()
        )
        comments_sub = (
            select(
                Comment.publication_id.label("pub_id"),
                func.count().label("stored"),
            )
            .where(Comment.is_deleted.is_(False))
            .group_by(Comment.publication_id)
            .subquery()
        )

        real = func.coalesce(metrics_sub.c.real, 0)
        stored = func.coalesce(comments_sub.c.stored, 0)

        q = (
            select(
                func.count(Publication.id),
                func.coalesce(func.sum(real), 0),
                func.coalesce(func.sum(stored), 0),
                func.coalesce(func.sum(func.greatest(real - stored, 0)), 0),
            )
            .select_from(Publication)
            .outerjoin(metrics_sub, metrics_sub.c.pub_id == Publication.id)
            .outerjoin(comments_sub, comments_sub.c.pub_id == Publication.id)
            .where(Publication.public_social_link_id == link_id)
            .where(Publication.published_at >= window_start)
        )

        row = (await self.db.execute(q)).one()
        return WindowDiff(
            posts_in_window=int(row[0] or 0),
            real_comments=int(row[1] or 0),
            stored_comments=int(row[2] or 0),
            unparsed=int(row[3] or 0),
        )

    async def mark_checked(self, link_id: UUID, when: datetime | None = None) -> None:
        """Ставит last_autoparse_at и сбрасывает ошибку — период проверки для
        ссылки закрыт успешно."""

        link = await self.db.get(PublicSocialLink, link_id)
        if link is not None:
            link.last_autoparse_at = when or datetime.now(timezone.utc)
            link.last_autoparse_error = None

    async def record_error(self, link_id: UUID, error: str | None) -> bool:
        """Фиксирует последнюю ошибку/причину пропуска по ссылке.

        last_autoparse_at намеренно НЕ трогаем: ссылка остаётся «созревшей» и
        будет повторена на следующем тике, а текст ошибки виден в интерфейсе.

        Возвращает True, если ошибка новая или изменилась. По этому признаку
        решают, слать ли её в трекер: ссылка со стойким отказом даёт одну и ту
        же ошибку каждый тик, и за месяц так набралось 443 одинаковых события.
        """

        link = await self.db.get(PublicSocialLink, link_id)
        if link is None:
            return False
        changed = link.last_autoparse_error != error
        link.last_autoparse_error = error
        return changed
