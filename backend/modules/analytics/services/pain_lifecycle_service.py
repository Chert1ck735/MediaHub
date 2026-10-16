"""Жизненный цикл боли и измерение Reaction Gap."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.enums import PainStatusEnum
from backend.modules.analytics.repositories.comment_repository import CommentRepository
from backend.modules.analytics.repositories.event_repository import EventRepository


class PainLifecycleService:
    """Статус боли и расчёт Reaction Gap (бизнес-логика поверх репозиториев)."""

    def __init__(
        self,
        db: AsyncSession,
        *,
        comment_repository: CommentRepository | None = None,
        event_repository: EventRepository | None = None,
    ) -> None:
        self._db = db
        self._comment_repository = comment_repository or CommentRepository(db)
        self._event_repository = event_repository or EventRepository(db)

    @staticmethod
    def _decide_status(
        events_count: int,
        last_post_at: datetime | None,
        before: int,
        after: int,
        recent: int,
    ) -> PainStatusEnum:
        """Правила жизненного цикла по уже посчитанным метрикам.

          1. Нет событий / нет поста → active.
          2. До поста упоминаний не было: вернулись (>5 за неделю) → in_progress,
             иначе → resolved.
          3. Упали ≥50 % после поста и за неделю мало → resolved.
          4. Иначе → in_progress.
        """

        if events_count == 0 or last_post_at is None:
            return PainStatusEnum.active
        if before == 0:
            return PainStatusEnum.in_progress if recent > 5 else PainStatusEnum.resolved
        drop_pct = (before - after) / before * 100.0
        if drop_pct >= 50.0 and recent <= 5:
            return PainStatusEnum.resolved
        return PainStatusEnum.in_progress

    async def compute_status(
        self,
        pain_id: uuid.UUID,
        *,
        quiet_days: int = 14,
    ) -> PainStatusEnum:
        """Состояние одной боли (чистое чтение БД, статус не сохраняется)."""

        events_count = await self._event_repository.count_events_for_pain(pain_id)
        if events_count == 0:
            return PainStatusEnum.active

        last_post_at = await self._event_repository.latest_post_at_for_pain(pain_id)
        if last_post_at is None:
            return PainStatusEnum.active
        if last_post_at.tzinfo is None:
            last_post_at = last_post_at.replace(tzinfo=timezone.utc)

        before = await self._comment_repository.count_pain_comments_between(
            pain_id, start=last_post_at - timedelta(days=quiet_days), end=last_post_at
        )
        after = await self._comment_repository.count_pain_comments_between(
            pain_id, start=last_post_at, end=last_post_at + timedelta(days=quiet_days)
        )
        recent = await self._comment_repository.count_pain_comments_between(
            pain_id, start=datetime.now(timezone.utc) - timedelta(days=7)
        )
        return self._decide_status(events_count, last_post_at, before, after, recent)

    async def compute_statuses(
        self,
        pain_ids: list[uuid.UUID],
        *,
        quiet_days: int = 14,
    ) -> dict[uuid.UUID, PainStatusEnum]:
        """Состояния пачки болей. Дешёвые метрики батчем, окна до/после — только
        по болям с постом."""

        if not pain_ids:
            return {}

        events = await self._event_repository.count_events_by_pains(pain_ids)
        last_posts = await self._event_repository.latest_post_at_by_pains(pain_ids)
        week_ago = datetime.now(timezone.utc) - timedelta(days=7)
        recent = await self._comment_repository.count_comments_since_by_pains(
            pain_ids, start=week_ago
        )

        statuses: dict[uuid.UUID, PainStatusEnum] = {}
        for pain_id in pain_ids:
            events_count = events.get(pain_id, 0)
            last_post_at = last_posts.get(pain_id)
            if events_count == 0 or last_post_at is None:
                statuses[pain_id] = PainStatusEnum.active
                continue
            if last_post_at.tzinfo is None:
                last_post_at = last_post_at.replace(tzinfo=timezone.utc)
            before = await self._comment_repository.count_pain_comments_between(
                pain_id, start=last_post_at - timedelta(days=quiet_days), end=last_post_at
            )
            after = await self._comment_repository.count_pain_comments_between(
                pain_id, start=last_post_at, end=last_post_at + timedelta(days=quiet_days)
            )
            statuses[pain_id] = self._decide_status(
                events_count, last_post_at, before, after, recent.get(pain_id, 0)
            )
        return statuses

    async def compute_reaction_gap(
        self,
        pain_id: uuid.UUID,
        *,
        window_days: int = 14,
    ) -> dict[str, Any]:
        """Reaction Gap по всем постам, привязанным к боли через события.

        Для каждого опубликованного/запланированного поста считаем число
        комментариев по этой боли в окне ``window_days`` ДО и ПОСЛЕ
        опорной даты. ``gap_pct > 0`` означает падение упоминаний (хорошо),
        ``< 0`` — рост. Боли без ``post.event_id`` в расчёте не участвуют.
        """

        posts_rows = await self._event_repository.list_posts_for_pain(pain_id)
        events: list[dict[str, Any]] = []
        deltas: list[float] = []
        for pid, ptitle, published_at, scheduled_at in posts_rows:
            anchor = published_at or scheduled_at
            if anchor is None:
                continue
            if anchor.tzinfo is None:
                anchor = anchor.replace(tzinfo=timezone.utc)

            before_count = await self._comment_repository.count_pain_comments_between(
                pain_id,
                start=anchor - timedelta(days=window_days),
                end=anchor,
            )
            after_count = await self._comment_repository.count_pain_comments_between(
                pain_id,
                start=anchor,
                end=anchor + timedelta(days=window_days),
            )
            if before_count == 0:
                gap_pct: float | None = None
            else:
                gap_pct = round((before_count - after_count) / before_count * 100.0, 1)
                deltas.append(gap_pct)

            events.append({
                "post_id": str(pid),
                "post_title": ptitle,
                "anchor_at": anchor.isoformat(),
                "window_days": window_days,
                "before_count": before_count,
                "after_count": after_count,
                "gap_pct": gap_pct,
            })

        avg = round(sum(deltas) / len(deltas), 1) if deltas else None
        return {
            "avg_gap_pct": avg,
            "measured_events": len(deltas),
            "events": events,
        }
