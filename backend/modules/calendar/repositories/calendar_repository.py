"""SQL-репозиторий календаря."""
from datetime import datetime
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from backend.db import Post, PublicSocialLink, Publication, EventPain, Pain, Public


class CalendarRepository:
    """Инкапсулирует SQL-запросы календарного модуля."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # Потолок на случай запроса без окна.
    LIST_LIMIT = 5000

    @staticmethod
    def _shown_at():
        """Дата, по которой публикация показывается в календаре."""

        return case(
            ((Publication.status == "scheduled") & Publication.scheduled_at.is_not(None), Publication.scheduled_at),
            else_=func.coalesce(Publication.published_at, Publication.scheduled_at, Publication.created_at),
        )

    async def list_calendar_publications(
        self, organization_id, *, date_from=None, date_to=None, link_ids=None,
        per_day=None, timezone_name="UTC", limit=None, offset=0,
    ):
        """Rank narrow publication rows before loading content and relationships.

        A post can occur on multiple dates/platforms. Count and paginate actual
        publications, using the viewer's timezone for both previews and totals.
        """
        shown_at = self._shown_at()
        day = func.date(func.timezone(timezone_name, shown_at))
        ranked_query = (
            select(
                Publication.id.label("id"), shown_at.label("shown_at"),
                func.count().over(partition_by=day).label("day_total"),
                func.row_number().over(
                    partition_by=day, order_by=(shown_at, Publication.id),
                ).label("place"),
            )
            .join(Post, Post.id == Publication.post_id)
            .where(Post.organization_id == organization_id)
        )
        ranked = self._apply_window(ranked_query, date_from, date_to, link_ids).subquery()
        chosen = select(ranked).order_by(ranked.c.shown_at, ranked.c.id)
        if per_day is not None:
            chosen = chosen.where(ranked.c.place <= per_day)
        else:
            if limit is not None:
                chosen = chosen.limit(limit)
            elif date_from is None or date_to is None:
                chosen = chosen.order_by(None).order_by(ranked.c.shown_at.desc(), ranked.c.id).limit(self.LIST_LIMIT)
            chosen = chosen.offset(offset)
        page = chosen.subquery()
        post_loader = joinedload(Publication.post)
        if per_day is not None:
            post_loader = post_loader.load_only(Post.id, Post.title, Post.origin, Post.status, Post.event_id)
        result = await self.db.execute(
            select(Publication, page.c.day_total)
            .join(page, page.c.id == Publication.id)
            .order_by(page.c.shown_at, Publication.id)
            .options(
                post_loader.joinedload(Post.event),
                joinedload(Publication.public_social_link).joinedload(PublicSocialLink.social_network),
            )
        )
        return list(result.unique().all())

    async def count_publications_by_day(
        self,
        organization_id,
        *,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        link_ids: list[str] | None = None,
    ) -> dict[str, int]:
        """Сколько публикаций в каждом дне окна.

        Сетке месяца нужно число «ещё» под ячейкой, а не сами записи: в дне
        их бывает под тысячу, и целиком месяц в ответ не помещается.
        """

        day = func.date(self._shown_at())
        query = (
            select(day.label("day"), func.count(func.distinct(Post.id)))
            .select_from(Post)
            .join(Post.publications)
            .where(Post.organization_id == organization_id)
        )
        query = self._apply_window(query, date_from, date_to, link_ids)
        rows = await self.db.execute(query.group_by(day))
        return {str(row[0]): int(row[1] or 0) for row in rows.all()}

    def _apply_window(self, query, date_from, date_to, link_ids):
        """Общие условия окна: даты показа и выбранные площадки."""

        shown_at = self._shown_at()
        query = query.where(Publication.status != "deleted")
        if date_from is not None:
            query = query.where(shown_at >= date_from)
        if date_to is not None:
            query = query.where(shown_at <= date_to)
        if link_ids:
            query = query.where(Publication.public_social_link_id.in_(link_ids))
        return query

    async def list_posts_with_publications(
        self,
        organization_id,
        *,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        link_ids: list[str] | None = None,
        per_day: int | None = None,
    ) -> list[Post]:
        """Посты организации с публикациями за окно показа.

        ``per_day`` оставляет по нескольку записей на день: сетке месяца
        больше и не нужно, а весь день целиком запрашивается отдельно, когда
        пользователь его открыл.
        """

        shown_at = self._shown_at()
        recent = select(
            Post.id.label("id"),
            func.max(shown_at).label("shown_at"),
            func.date(func.max(shown_at)).label("day"),
        ).join(Post.publications).where(Post.organization_id == organization_id)
        recent = self._apply_window(recent, date_from, date_to, link_ids).group_by(Post.id)

        recent_rows = recent.subquery()
        if per_day:
            ranked = select(
                recent_rows.c.id,
                func.row_number()
                .over(
                    partition_by=recent_rows.c.day,
                    order_by=(recent_rows.c.shown_at.desc(), recent_rows.c.id),
                )
                .label("place"),
            ).subquery()
            chosen = select(ranked.c.id).where(ranked.c.place <= per_day)
        else:
            chosen = select(recent_rows.c.id).order_by(recent_rows.c.shown_at.desc(), recent_rows.c.id)
            if date_from is None or date_to is None:
                chosen = chosen.limit(self.LIST_LIMIT)

        result = await self.db.execute(
            select(Post)
            .where(Post.id.in_(chosen))
            .order_by(Post.created_at.desc())
            .options(*self._list_load_options())
        )
        return list(result.scalars().unique().all())

    async def get_calendar_post(self, post_id: str, organization_id) -> Post | None:
        """Возвращает один календарный пост организации."""

        result = await self.db.execute(
            select(Post)
            .where(Post.id == post_id, Post.organization_id == organization_id)
            .options(*self._post_load_options())
        )
        return result.scalar_one_or_none()

    async def get_public_social_link(self, link_id: str, organization_id) -> PublicSocialLink | None:
        """Возвращает активную ссылку площадки с загруженной social_network."""

        result = await self.db.execute(
            select(PublicSocialLink)
            .join(Public, Public.id == PublicSocialLink.public_id)
            .where(Public.organization_id == organization_id)
            .where(PublicSocialLink.id == link_id)
            .where(PublicSocialLink.is_active.is_(True))
            .options(selectinload(PublicSocialLink.social_network))
        )
        return result.scalar_one_or_none()

    async def fetch_event_pain_links(self, event_id) -> list[dict[str, str]]:
        """Возвращает боли, привязанные к инфоповоду."""

        if not event_id:
            return []
        rows = await self.db.execute(
            select(EventPain.pain_id, Pain.title)
            .select_from(EventPain)
            .join(Pain, Pain.id == EventPain.pain_id)
            .where(EventPain.event_id == event_id)
        )
        return [{"pain_id": str(pid), "pain_title": title} for pid, title in rows.all()]

    async def fetch_event_pain_links_map(self, event_ids: set) -> dict[Any, list[dict[str, str]]]:
        """Возвращает боли по нескольким инфоповодам одним запросом."""

        if not event_ids:
            return {}

        rows = await self.db.execute(
            select(EventPain.event_id, EventPain.pain_id, Pain.title)
            .select_from(EventPain)
            .join(Pain, Pain.id == EventPain.pain_id)
            .where(EventPain.event_id.in_(event_ids))
        )
        result: dict[Any, list[dict[str, str]]] = {}
        for event_id, pain_id, pain_title in rows.all():
            result.setdefault(event_id, []).append(
                {"pain_id": str(pain_id), "pain_title": pain_title}
            )
        return result

    async def add_publication(self, publication: Publication) -> Publication:
        """Добавляет публикацию в текущую транзакцию."""

        self.db.add(publication)
        await self.db.flush()
        return publication

    async def delete_publication(self, publication: Publication) -> None:
        """Удаляет публикацию в текущей транзакции."""

        await self.db.delete(publication)

    async def flush(self) -> None:
        """Синхронизирует изменения с БД без commit."""

        await self.db.flush()

    async def commit(self) -> None:
        """Фиксирует транзакцию."""

        await self.db.commit()

    def _list_load_options(self):
        """То же, но без стратегий: списку календаря они не нужны.

        Постов у организации тысячи, и каждая лишняя связь — отдельный запрос
        и лишние объекты в памяти на весь ответ.
        """

        return (
            selectinload(Post.publications)
            .selectinload(Publication.public_social_link)
            .selectinload(PublicSocialLink.social_network),
            selectinload(Post.event),
        )

    def _post_load_options(self):
        """Возвращает eager-load опции для календарного поста."""

        return (
            selectinload(Post.publications)
            .selectinload(Publication.public_social_link)
            .selectinload(PublicSocialLink.social_network),
            selectinload(Post.strategy_links),
            selectinload(Post.event),
        )
