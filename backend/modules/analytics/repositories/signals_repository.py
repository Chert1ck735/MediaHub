"""Сырые агрегатные выборки по комментариям VK для summary-эндпоинта."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Sequence

from sqlalchemy import Row, func, literal_column, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.comment_analysis import CommentAnalysis
from backend.db.comment_pains import CommentPain
from backend.db.comments import Comment
from backend.db.enums import RelevanceEnum
from backend.db.pains import Pain
from backend.db.public_social_links import PublicSocialLink
from backend.db.publications import Publication
from backend.db.publics import Public
from backend.db.snapshot_pains import SnapshotPain
from backend.db.social_networks import SocialNetwork
from backend.db.users import User
from backend.modules.analytics.constants import (
    ANALYTICS_NETWORK_CODES,
    APPEAL_MESSAGE_TYPES,
    GRATITUDE_MESSAGE_TYPES,
)
from backend.modules.analytics.utils.public_link_filter import (
    PublicSocialLinkFilter,
    apply_public_social_link_filter,
)
from backend.modules.analytics.utils.municipality_filter import (
    apply_comment_municipality_filter,
)


class SignalsRepository:
    """SQL-доступ к агрегатам комментариев для /summary."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    @staticmethod
    def _apply_period(query, since: datetime | None, until: datetime | None = None):
        """Ограничение по реальной дате комментария в VK (fallback — время импорта).

        ``until`` задаётся только для сравнения с прошлым периодом: обычные
        запросы аналитики верхней границы не имеют и не должны её получать.
        """
        at = func.coalesce(Comment.comment_date, Comment.created_at)
        if since is not None:
            query = query.where(at >= since)
        if until is not None:
            query = query.where(at < until)
        return query

    @staticmethod
    def _apply_link(query, link_id: PublicSocialLinkFilter):
        """Фильтр площадки и исключение ответов сообщества."""
        query = query.where(
            or_(
                Comment.author_external_id.is_(None),
                ~Comment.author_external_id.like("-%"),
            )
        )
        return apply_public_social_link_filter(
            query,
            Publication.public_social_link_id,
            link_id,
        )

    @staticmethod
    def _citizen_analysis(query):
        """Отсекает официальные ответы: единица аналитики — сообщение пользователя."""
        return query.where(
            func.coalesce(CommentAnalysis.is_official_response, False).is_(False)
        )

    def _filtered(self, query, *, since, link_id, municipality_name: str | None = None, until=None):
        return apply_comment_municipality_filter(
            self._apply_link(self._apply_period(query, since, until), link_id),
            municipality_name,
        )

    async def count_total_comments(
        self,
        user: User,
        *,
        since: datetime | None,
        link_id: PublicSocialLinkFilter,
        municipality_name: str | None = None,
    ) -> int:
        query = (
            select(func.count(Comment.id))
            .select_from(Comment)
            .join(CommentAnalysis, CommentAnalysis.comment_id == Comment.id, isouter=True)
            .join(Publication, Publication.id == Comment.publication_id)
            .join(PublicSocialLink, PublicSocialLink.id == Publication.public_social_link_id)
            .join(SocialNetwork, SocialNetwork.id == PublicSocialLink.social_network_id)
            .join(Public, Public.id == PublicSocialLink.public_id)
            .where(Public.organization_id == user.organization_id)
            .where(SocialNetwork.code.in_(ANALYTICS_NETWORK_CODES))
            .where(Comment.is_deleted.is_(False))
        )
        return int((await self._db.execute(
            self._filtered(query, since=since, link_id=link_id, municipality_name=municipality_name)
        )).scalar() or 0)

    async def count_classified_comments(
        self,
        user: User,
        *,
        since: datetime | None,
        link_id: PublicSocialLinkFilter,
        municipality_name: str | None = None,
    ) -> int:
        """Сколько комментов уже обработано воркером (classification_state='done').

        Оффтоп/нерелевантность/официальные ответы тоже сюда — это результат
        классификации, не «не обработано». Исключать официальные ответы нельзя:
        «собрано» их содержит (отличить ответ представителя организации с личного аккаунта
        можно только ПОСЛЕ анализа), и воронка навсегда не сходилась бы.
        """
        query = (
            select(func.count(func.distinct(Comment.id)))
            .select_from(Comment)
            .join(CommentAnalysis, CommentAnalysis.comment_id == Comment.id)
            .join(Publication, Publication.id == Comment.publication_id)
            .join(PublicSocialLink, PublicSocialLink.id == Publication.public_social_link_id)
            .join(SocialNetwork, SocialNetwork.id == PublicSocialLink.social_network_id)
            .join(Public, Public.id == PublicSocialLink.public_id)
            .where(Public.organization_id == user.organization_id)
            .where(SocialNetwork.code.in_(ANALYTICS_NETWORK_CODES))
            .where(Comment.is_deleted.is_(False))
            .where(CommentAnalysis.classification_state == "done")
        )
        return int((await self._db.execute(
            self._filtered(query, since=since, link_id=link_id, municipality_name=municipality_name)
        )).scalar() or 0)

    async def count_relevant_comments(
        self,
        snapshot_uuid: uuid.UUID,
        *,
        since: datetime | None,
        link_id: PublicSocialLinkFilter,
        municipality_name: str | None = None,
    ) -> int:
        query = (
            select(func.count(func.distinct(CommentPain.comment_id)))
            .select_from(CommentPain)
            .join(Pain, Pain.id == CommentPain.pain_id)
            .join(SnapshotPain, SnapshotPain.pain_id == Pain.id)
            .join(Comment, Comment.id == CommentPain.comment_id)
            .join(Publication, Publication.id == Comment.publication_id)
            .join(PublicSocialLink, PublicSocialLink.id == Publication.public_social_link_id)
            .join(Public, Public.id == PublicSocialLink.public_id)
            .join(CommentAnalysis, CommentAnalysis.comment_id == Comment.id, isouter=True)
            .where(SnapshotPain.snapshot_id == snapshot_uuid)
            .where(Comment.is_deleted.is_(False))
        )
        return int((await self._db.execute(
            self._filtered(query, since=since, link_id=link_id, municipality_name=municipality_name)
        )).scalar() or 0)

    def _relevant_message_base(self, user: User):
        return self._citizen_analysis(
            select(func.count(func.distinct(CommentAnalysis.comment_id)))
            .select_from(CommentAnalysis)
            .join(Comment, Comment.id == CommentAnalysis.comment_id)
            .join(Publication, Publication.id == Comment.publication_id)
            .join(PublicSocialLink, PublicSocialLink.id == Publication.public_social_link_id)
            .join(SocialNetwork, SocialNetwork.id == PublicSocialLink.social_network_id)
            .join(Public, Public.id == PublicSocialLink.public_id)
            .where(Public.organization_id == user.organization_id)
            .where(SocialNetwork.code.in_(ANALYTICS_NETWORK_CODES))
            .where(Comment.is_deleted.is_(False))
            .where(CommentAnalysis.classification_state == "done")
            .where(CommentAnalysis.relevance == RelevanceEnum.relevant)
        )

    async def count_relevant_by_message_types(
        self,
        user: User,
        *,
        message_types: list[str],
        since: datetime | None,
        link_id: PublicSocialLinkFilter,
        municipality_name: str | None = None,
        until: datetime | None = None,
    ) -> int:
        query = self._relevant_message_base(user).where(
            CommentAnalysis.message_type.in_(message_types)
        )
        return int((await self._db.execute(
            self._filtered(query, since=since, link_id=link_id, municipality_name=municipality_name, until=until)
        )).scalar() or 0)

    def _vk_analysis_group_base(self, user: User, *columns):
        """База разбивок — та же, что в ``count_classified_comments``.

        Официальные ответы НЕ исключаются: тональность и типы должны давать
        в сумме число классифицированных. Где ответы организаций неуместны
        (обращения, благодарности, категории) — там ``_citizen_analysis``
        накладывается отдельно.
        """
        return (
            select(*columns)
            .select_from(CommentAnalysis)
            .join(Comment, Comment.id == CommentAnalysis.comment_id)
            .join(Publication, Publication.id == Comment.publication_id)
            .join(PublicSocialLink, PublicSocialLink.id == Publication.public_social_link_id)
            .join(SocialNetwork, SocialNetwork.id == PublicSocialLink.social_network_id)
            .join(Public, Public.id == PublicSocialLink.public_id)
            .where(Public.organization_id == user.organization_id)
            .where(SocialNetwork.code.in_(ANALYTICS_NETWORK_CODES))
            .where(Comment.is_deleted.is_(False))
            .where(CommentAnalysis.classification_state == "done")
        )

    async def count_appeals(
        self,
        user: User,
        *,
        since: datetime | None,
        link_id: PublicSocialLinkFilter,
        municipality_name: str | None = None,
        until: datetime | None = None,
    ) -> int:
        """Сообщения аудитории — единая база для SLA, категорий и карточки типов."""

        return await self.count_relevant_by_message_types(
            user,
            message_types=list(APPEAL_MESSAGE_TYPES),
            since=since,
            link_id=link_id,
            municipality_name=municipality_name,
            until=until,
        )

    async def count_gratitude(
        self,
        user: User,
        *,
        since: datetime | None,
        link_id: PublicSocialLinkFilter,
        municipality_name: str | None = None,
    ) -> int:
        """Благодарности по типу сообщения: relevance не требуем, они часто irrelevant."""

        query = self._citizen_analysis(
            self._vk_analysis_group_base(
                user, func.count(func.distinct(CommentAnalysis.comment_id))
            ).where(CommentAnalysis.message_type.in_(GRATITUDE_MESSAGE_TYPES))
        )
        return int((await self._db.execute(
            self._filtered(query, since=since, link_id=link_id, municipality_name=municipality_name)
        )).scalar() or 0)

    async def sentiment_rows(
        self,
        user: User,
        *,
        since: datetime | None,
        link_id: PublicSocialLinkFilter,
        municipality_name: str | None = None,
    ) -> Sequence[Row]:
        query = self._vk_analysis_group_base(
            user,
            CommentAnalysis.sentiment,
            func.count(func.distinct(CommentAnalysis.comment_id)),
        ).group_by(CommentAnalysis.sentiment)
        return (await self._db.execute(
            self._filtered(query, since=since, link_id=link_id, municipality_name=municipality_name)
        )).all()

    async def message_type_rows(
        self,
        user: User,
        *,
        since: datetime | None,
        link_id: PublicSocialLinkFilter,
        municipality_name: str | None = None,
    ) -> Sequence[Row]:
        query = self._vk_analysis_group_base(
            user,
            CommentAnalysis.message_type,
            func.count(func.distinct(CommentAnalysis.comment_id)),
        ).group_by(CommentAnalysis.message_type)
        return (await self._db.execute(
            self._filtered(query, since=since, link_id=link_id, municipality_name=municipality_name)
        )).all()

    async def category_rows(
        self,
        user: User,
        *,
        since: datetime | None,
        link_id: PublicSocialLinkFilter,
        municipality_name: str | None = None,
        until: datetime | None = None,
    ) -> Sequence[Row]:
        query = self._vk_analysis_group_base(
            user,
            func.coalesce(
                func.json_extract_path_text(CommentAnalysis.hierarchy, "category"), ""
            ).label("category"),
            func.count(func.distinct(CommentAnalysis.comment_id)).label("cnt"),
        ).where(
            CommentAnalysis.relevance == RelevanceEnum.relevant,
            CommentAnalysis.message_type.in_(APPEAL_MESSAGE_TYPES),
        ).group_by(literal_column("category"))
        query = self._citizen_analysis(query)
        return (await self._db.execute(
            self._filtered(
                query,
                since=since,
                link_id=link_id,
                municipality_name=municipality_name,
                until=until,
            )
        )).all()

    async def category_sentiment_rows(
        self,
        user: User,
        *,
        since: datetime | None,
        link_id: PublicSocialLinkFilter,
        municipality_name: str | None = None,
    ) -> Sequence[Row]:
        query = self._vk_analysis_group_base(
            user,
            func.coalesce(
                func.json_extract_path_text(CommentAnalysis.hierarchy, "category"), ""
            ).label("category"),
            CommentAnalysis.sentiment,
            func.count(func.distinct(CommentAnalysis.comment_id)).label("cnt"),
        ).where(
            CommentAnalysis.relevance == RelevanceEnum.relevant,
            CommentAnalysis.message_type.in_(APPEAL_MESSAGE_TYPES),
        ).group_by(
            literal_column("category"), CommentAnalysis.sentiment
        )
        query = self._citizen_analysis(query)
        return (await self._db.execute(
            self._filtered(query, since=since, link_id=link_id, municipality_name=municipality_name)
        )).all()

    def _vk_comment_time_base(self, user: User, extract_part: str, label: str):
        return (
            select(
                func.extract(
                    extract_part,
                    func.coalesce(Comment.comment_date, Comment.created_at),
                ).label(label),
                func.count(Comment.id).label("n"),
            )
            .select_from(Comment)
            .join(CommentAnalysis, CommentAnalysis.comment_id == Comment.id, isouter=True)
            .join(Publication, Publication.id == Comment.publication_id)
            .join(PublicSocialLink, PublicSocialLink.id == Publication.public_social_link_id)
            .join(SocialNetwork, SocialNetwork.id == PublicSocialLink.social_network_id)
            .join(Public, Public.id == PublicSocialLink.public_id)
            .where(Public.organization_id == user.organization_id)
            .where(SocialNetwork.code.in_(ANALYTICS_NETWORK_CODES))
            .where(Comment.is_deleted.is_(False))
            .group_by(literal_column(label))
            .order_by(literal_column("n").desc())
        )

    async def hour_rows(
        self,
        user: User,
        *,
        since: datetime | None,
        link_id: PublicSocialLinkFilter,
        municipality_name: str | None = None,
    ) -> Sequence[Row]:
        query = self._vk_comment_time_base(user, "hour", "h")
        return (await self._db.execute(
            self._filtered(query, since=since, link_id=link_id, municipality_name=municipality_name)
        )).all()

    async def dow_rows(
        self,
        user: User,
        *,
        since: datetime | None,
        link_id: PublicSocialLinkFilter,
        municipality_name: str | None = None,
    ) -> Sequence[Row]:
        query = self._vk_comment_time_base(user, "dow", "d")
        return (await self._db.execute(
            self._filtered(query, since=since, link_id=link_id, municipality_name=municipality_name)
        )).all()
