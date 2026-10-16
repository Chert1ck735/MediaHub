"""Доступ к данным болей, их доказательствам и стратегиям.

Запросы по ``Pain``, ``PainEvidence``, ``PainStrategy``. Нормализация
текстов комментариев под формат API делегирована в утилиты
``comment_examples`` и ``text_normalize``.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.comment_analysis import CommentAnalysis
from backend.db.comment_pains import CommentPain
from backend.db.comments import Comment
from backend.db.pain_evidence import PainEvidence
from backend.db.pain_strategies import PainStrategy
from backend.db.pains import Pain
from backend.db.publications import Publication
from backend.db.public_social_links import PublicSocialLink
from backend.db.publics import Public
from backend.db.users import User
from backend.modules.analytics.repositories.comment_repository import CommentRepository
from backend.modules.analytics.utils.comment_examples import vk_comment_url
from backend.modules.analytics.utils.municipality_filter import apply_comment_municipality_filter
from backend.modules.analytics.utils.public_link_filter import (
    PublicSocialLinkFilter,
    apply_public_social_link_filter,
)
from backend.modules.analytics.utils.text_normalize import trim_text


class PainRepository:
    """SQL-доступ к ``Pain`` и связанным сущностям."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def get_by_id(self, pain_id: str, user: User) -> Pain | None:
        """Возвращает боль по id с проверкой принадлежности организации пользователя."""

        pain_uuid = uuid.UUID(pain_id)
        result = await self._db.execute(
            select(Pain)
            .where(Pain.id == pain_uuid, Pain.organization_id == user.organization_id)
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_evidence_urls(self, pain_id: str) -> list[str]:
        """Список URL-доказательств боли в порядке их добавления."""

        pain_uuid = uuid.UUID(pain_id)
        result = await self._db.execute(
            select(PainEvidence.url)
            .where(PainEvidence.pain_id == pain_uuid)
            .order_by(PainEvidence.created_at.asc())
        )
        return [row[0] for row in result.all()]

    async def get_evidence_urls_map(self, pain_ids: list[str]) -> dict[str, list[str]]:
        """То же, что ``get_evidence_urls``, но сразу на список болей.

        Поштучно это запрос на каждую карточку списка.
        """

        if not pain_ids:
            return {}
        uuids = [uuid.UUID(pain_id) for pain_id in pain_ids]
        result = await self._db.execute(
            select(PainEvidence.pain_id, PainEvidence.url)
            .where(PainEvidence.pain_id.in_(uuids))
            .order_by(PainEvidence.created_at.asc())
        )
        urls: dict[str, list[str]] = {}
        for pain_id, url in result.all():
            urls.setdefault(str(pain_id), []).append(url)
        return urls

    async def get_strategies_map(self, pain_ids: list[str]) -> dict[str, list[tuple[str, str]]]:
        """Пары «идентификатор, описание» стратегий для списка болей за один запрос."""

        if not pain_ids:
            return {}
        uuids = [uuid.UUID(pain_id) for pain_id in pain_ids]
        result = await self._db.execute(
            select(PainStrategy.pain_id, PainStrategy.id, PainStrategy.description)
            .where(PainStrategy.pain_id.in_(uuids))
            .order_by(PainStrategy.created_at.asc())
        )
        strategies: dict[str, list[tuple[str, str]]] = {}
        for pain_id, strategy_id, description in result.all():
            strategies.setdefault(str(pain_id), []).append((str(strategy_id), description))
        return strategies

    async def get_comment_examples(
        self,
        pain_id: str,
        *,
        link_id: PublicSocialLinkFilter = None,
        municipality_name: str | None = None,
    ) -> list[dict[str, Any]]:
        """Развёрнутые примеры комментариев, привязанных к боли через ``PainEvidence``.

        ``link_id`` — фильтр по площадке: оставляем только evidence,
        чья публикация принадлежит выбранному PublicSocialLink.
        """

        pain_uuid = uuid.UUID(pain_id)
        stmt = (
            select(
                PainEvidence.comment_id,
                PainEvidence.url,
                PainEvidence.note,
                Comment.text,
                Comment.external_id,
                Publication.url.label("publication_url"),
                CommentAnalysis.message_type,
                CommentAnalysis.sentiment,
            )
            .select_from(PainEvidence)
            .join(Comment, Comment.id == PainEvidence.comment_id, isouter=True)
            .join(Publication, Publication.id == PainEvidence.publication_id, isouter=True)
            .join(PublicSocialLink, PublicSocialLink.id == Publication.public_social_link_id, isouter=True)
            .join(Public, Public.id == PublicSocialLink.public_id, isouter=True)
            .join(CommentAnalysis, CommentAnalysis.comment_id == Comment.id, isouter=True)
            .where(PainEvidence.pain_id == pain_uuid)
            .order_by(PainEvidence.created_at.asc())
        )
        stmt = apply_public_social_link_filter(
            stmt,
            Publication.public_social_link_id,
            link_id,
        )
        stmt = apply_comment_municipality_filter(stmt, municipality_name)
        result = await self._db.execute(stmt)
        items: list[dict[str, Any]] = []
        seen: set[tuple[str, str | None]] = set()
        for row in result.all():
            publication_url = row.publication_url or row.url
            url = vk_comment_url(publication_url, row.external_id) or publication_url
            text = trim_text(str(row.text or row.note or ""), 320)
            if not text:
                continue
            key = (text, url)
            if key in seen:
                continue
            seen.add(key)
            items.append(
                {
                    "text": text,
                    "url": url,
                    "publication_url": publication_url,
                    "comment_id": str(row.comment_id) if row.comment_id else None,
                    "message_type": row.message_type,
                    "sentiment": row.sentiment.value if row.sentiment else None,
                }
            )
        return items

    async def list_pain_comment_mentions(
        self,
        user: User,
        *,
        since: datetime | None,
        link_id: PublicSocialLinkFilter = None,
        municipality_name: str | None = None,
    ) -> list[tuple[uuid.UUID, uuid.UUID, datetime | None]]:
        """Distinct ``(pain_id, comment_id, дата)`` по болям организации.

        Дата = реальная дата коммента в VK (``comment_date``, fallback ``created_at``).
        При ``since=None`` период не фильтруется (окно якорит сервис). Раскладку по неделям делает сервис.
        """

        at = func.coalesce(Comment.comment_date, Comment.created_at)
        q = CommentRepository.appeal_scope(
            select(CommentPain.pain_id, CommentPain.comment_id, at.label("at"))
            .select_from(CommentPain)
            .join(Comment, Comment.id == CommentPain.comment_id)
            .join(CommentAnalysis, CommentAnalysis.comment_id == Comment.id)
            .join(Publication, Publication.id == Comment.publication_id)
            .join(PublicSocialLink, PublicSocialLink.id == Publication.public_social_link_id)
            .join(Public, Public.id == PublicSocialLink.public_id)
            .join(Pain, Pain.id == CommentPain.pain_id)
            .where(Pain.organization_id == user.organization_id)
            .where(Comment.is_deleted.is_(False))
            .distinct()
        )
        if since is not None:
            q = q.where(at >= since)
        q = apply_public_social_link_filter(
            q,
            Publication.public_social_link_id,
            link_id,
        )
        q = apply_comment_municipality_filter(q, municipality_name)
        return list((await self._db.execute(q)).all())

    async def get_strategy_ids(self, pain_id: str) -> list[str]:
        """Идентификаторы стратегий коммуникации, привязанных к боли."""

        pain_uuid = uuid.UUID(pain_id)
        result = await self._db.execute(
            select(PainStrategy.id)
            .where(PainStrategy.pain_id == pain_uuid)
            .order_by(PainStrategy.created_at.asc())
        )
        return [str(row[0]) for row in result.all()]

    async def get_strategy_descriptions(self, pain_id: str) -> list[str]:
        """Сырые тексты стратегий — без очистки.

        Очистку (``_clean_strategy_text``) делает сервисный слой, потому
        что она зависит от текущего форматирования сообщений LLM и может
        меняться отдельно от схемы БД.
        """

        pain_uuid = uuid.UUID(pain_id)
        result = await self._db.execute(
            select(PainStrategy.description)
            .where(PainStrategy.pain_id == pain_uuid)
            .order_by(PainStrategy.created_at.asc())
        )
        return [row[0] for row in result.all()]
