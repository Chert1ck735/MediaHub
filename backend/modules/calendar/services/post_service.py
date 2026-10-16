"""Сервис постов календаря."""
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from backend.db import Post, User
from backend.modules.calendar.utils.errors import CalendarNotFoundError
from backend.modules.calendar.utils.interfaces import CalendarRepositoryProtocol
from backend.modules.posts import service as posts_service


class CalendarPostService:
    """Создает, обновляет и загружает посты календаря."""

    def __init__(self, db: AsyncSession, repository: CalendarRepositoryProtocol) -> None:
        """Сохраняет зависимости сервиса постов."""
        self.db = db
        self.repository = repository

    async def create_or_update_post(
        self,
        *,
        user: User,
        post_id: str | None,
        title: str,
        description: str,
        draft: str,
        tone: str,
    ) -> Post:
        """Создает новый пост или обновляет существующий."""
        if post_id:
            post = await posts_service.load_post_for_user(
                self.db,
                post_id,
                user.organization_id,
                with_publications=True,
            )
            if not post:
                raise CalendarNotFoundError("Пост не найден")
            self.fill_post(post=post, title=title, description=description, draft=draft, tone=tone)
            return post

        created = await posts_service.create_post(
            self.db,
            user,
            title=title,
            text_draft=description,
            text_generated=draft,
            tone=tone,
            vk_post_id=None,
            strategy_id=None,
        )
        post = await self.repository.get_calendar_post(str(created.id), user.organization_id)
        if not post:
            raise CalendarNotFoundError("Созданный пост не найден")
        return post

    async def require_post(self, post_id: str, organization_id) -> Post:
        """Возвращает календарный пост или выбрасывает ошибку."""
        post = await self.repository.get_calendar_post(post_id, organization_id)
        if not post:
            raise CalendarNotFoundError("Событие не найдено")
        return post

    def fill_post(
        self,
        *,
        post: Post,
        title: str,
        description: str,
        draft: str,
        tone: str,
    ) -> None:
        """Заполняет поля Post из календарного payload."""
        post.title = title
        post.text_draft = description
        post.text_generated = draft
        post.text_final = posts_service.build_text_final(draft, tone)
        post.summary = ((draft or description)[:500] or None)

    def apply_info_event(
        self,
        post: Post,
        info_event_id: str | None,
        *,
        reset_on_invalid: bool,
    ) -> None:
        """Привязывает пост к инфоповоду Event."""
        if info_event_id is None:
            return
        try:
            post.event_id = uuid.UUID(info_event_id) if info_event_id else None
        except (ValueError, TypeError):
            if reset_on_invalid:
                post.event_id = None
