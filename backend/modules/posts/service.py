"""Бизнес-сценарии posts.

Сервис создает, обновляет и удаляет посты, а детали SQL, сериализации,
текста и rollup-полей вынесены в отдельные модули.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.enums import ContentTypeEnum, PostOriginEnum, PublicationStatusEnum
from backend.db.posts import Post
from backend.db.users import User
from backend.modules.audit_utils import add_action_log
from backend.modules.metadata_utils import get_or_create_data_source, link_post_to_strategy, sync_post_tags
from backend.modules.posts.content import (
    build_text_final as _build_text_final,
    extract_post_tone as _extract_post_tone,
    post_summary,
)
from backend.modules.posts.utils.errors import PostError
from backend.modules.posts.repositories.post_repository import PostRepository
from backend.modules.posts.utils.rollups import refresh_post_rollups as apply_post_rollups


def _require_org(user: User):
    """Достает организацию пользователя или останавливает сценарий понятной ошибкой."""
    if not user.organization_id:
        raise PostError("У пользователя не задана организация")
    return user.organization_id


def _origin_for_text(text_generated: str | None) -> PostOriginEnum:
    """Определяет происхождение поста по наличию сгенерированного текста."""
    return PostOriginEnum.llm_generated if (text_generated or "").strip() else PostOriginEnum.manual


async def _get_editor_data_source(db: AsyncSession, origin: PostOriginEnum):
    """Возвращает data source для постов, созданных через редактор."""
    generated = origin == PostOriginEnum.llm_generated
    return await get_or_create_data_source(
        db,
        source_type="manual",
        name="llm_ui_assist" if generated else "manual_ui",
        description="Создание постов через интерфейс редактора",
        configuration={"channel": "posts_ui", "generated": generated},
    )


class PostService:
    """Оркестрирует сценарии posts, не смешиваясь с HTTP и сырым SQL."""

    def __init__(self, db: AsyncSession):
        """Собирает зависимости сервиса вокруг одной database session."""
        self.db = db
        self.posts = PostRepository(db)

    async def load_post_for_user(
        self,
        post_id: str,
        organization_id,
        *,
        with_publications: bool = True,
    ) -> Post | None:
        """Загружает пост организации и нужные связи для дальнейшей работы."""
        return await self.posts.get_for_organization(
            post_id,
            organization_id,
            with_publications=with_publications,
        )

    async def list_posts(self, user: User) -> list[Post]:
        """Возвращает посты редактора и обновляет их rollup-поля в памяти."""
        organization_id = _require_org(user)
        posts = await self.posts.list_editor_posts(organization_id)
        for post in posts:
            apply_post_rollups(post)
        return posts

    async def create_post(
        self,
        user: User,
        title: str,
        text_draft: str,
        text_generated: str,
        tone: str,
        vk_post_id: str | None,
        strategy_id: str | None = None,
    ) -> Post:
        """Создает пост из редактора, связывает теги/стратегию и пишет audit log."""
        organization_id = _require_org(user)
        origin = _origin_for_text(text_generated)
        source = await _get_editor_data_source(self.db, origin)
        post = Post(
            title=title,
            text_draft=text_draft,
            text_generated=text_generated,
            text_final=_build_text_final(text_generated, tone),
            summary=post_summary(text_generated, text_draft),
            origin=origin,
            content_type=ContentTypeEnum.text,
            status=PublicationStatusEnum.pending,
            author_id=user.id,
            organization_id=organization_id,
            source_id=source.id,
        )
        await self.posts.add(post)
        await self.db.flush()
        await sync_post_tags(self.db, post, [origin.value, "text"])
        strategy_link = await link_post_to_strategy(self.db, strategy_id=strategy_id, post=post)
        add_action_log(
            self.db,
            user_id=user.id,
            action="post_created",
            entity_type="post",
            entity_id=post.id,
            details={
                "origin": origin.value,
                "status": post.status.value,
                "strategy_id": strategy_link.strategy_id if strategy_link else None,
                "vk_post_id": vk_post_id,
            },
        )
        await self.db.commit()
        return await self.load_post_for_user(str(post.id), organization_id, with_publications=True)

    async def update_post_vk(self, post_id: str, user: User, vk_post_id: str | None) -> Post | None:
        """Обновляет статус поста по факту публикации во VK."""
        organization_id = _require_org(user)
        post = await self.load_post_for_user(post_id, organization_id, with_publications=True)
        if not post:
            return None
        post.status = PublicationStatusEnum.published if vk_post_id else PublicationStatusEnum.pending
        add_action_log(
            self.db,
            user_id=user.id,
            action="post_vk_status_updated",
            entity_type="post",
            entity_id=post.id,
            details={"vk_post_id": vk_post_id, "status": post.status.value},
        )
        await self.db.commit()
        return await self.load_post_for_user(str(post.id), organization_id, with_publications=True)

    async def update_post(
        self,
        post_id: str,
        user: User,
        *,
        title: str | None = None,
        text_draft: str | None = None,
        text_generated: str | None = None,
        tone: str | None = None,
        strategy_id: str | None = None,
    ) -> Post | None:
        """Обновляет поля поста, пересобирает final text, теги, стратегию и audit log."""
        organization_id = _require_org(user)
        post = await self.load_post_for_user(post_id, organization_id, with_publications=True)
        if not post:
            return None

        if title is not None:
            post.title = title
        if text_draft is not None:
            post.text_draft = text_draft
        if text_generated is not None:
            post.text_generated = text_generated
            post.origin = _origin_for_text(text_generated)
            source = await _get_editor_data_source(self.db, post.origin)
            post.source_id = source.id

        next_tone = tone if tone is not None else _extract_post_tone(post)
        post.text_final = _build_text_final(post.text_generated or "", next_tone)
        post.summary = post_summary(post.text_generated, post.text_draft)

        await sync_post_tags(self.db, post, [post.origin.value if post.origin else "manual", "text"])
        strategy_link = await link_post_to_strategy(self.db, strategy_id=strategy_id, post=post)
        add_action_log(
            self.db,
            user_id=user.id,
            action="post_updated",
            entity_type="post",
            entity_id=post.id,
            details={
                "status": post.status.value,
                "strategy_id": strategy_link.strategy_id if strategy_link else None,
                "updated_fields": {
                    "title": title is not None,
                    "text_draft": text_draft is not None,
                    "text_generated": text_generated is not None,
                    "tone": tone is not None,
                },
            },
        )
        await self.db.commit()
        return await self.load_post_for_user(str(post.id), organization_id, with_publications=True)

    async def delete_post(self, post_id: str, user: User) -> bool:
        """Удаляет пост организации и пишет audit log."""
        organization_id = _require_org(user)
        post = await self.load_post_for_user(post_id, organization_id, with_publications=True)
        if not post:
            return False
        add_action_log(
            self.db,
            user_id=user.id,
            action="post_deleted",
            entity_type="post",
            entity_id=post.id,
            details={"status": post.status.value},
        )
        await self.posts.delete(post)
        await self.db.commit()
        return True


# Функции-обертки оставлены для старых импортов из calendar/publications.
def extract_post_tone(post: Post) -> str:
    """Совместимость со старым API: делегирует извлечение тона в content helper."""
    return _extract_post_tone(post)


def build_text_final(text_generated: str, tone: str) -> str:
    """Совместимость со старым API: делегирует сборку финального текста в content helper."""
    return _build_text_final(text_generated, tone)


async def load_post_for_user(
    db: AsyncSession,
    post_id: str,
    organization_id,
    *,
    with_publications: bool = True,
) -> Post | None:
    """Совместимость со старым API: делегирует загрузку поста в PostService."""
    return await PostService(db).load_post_for_user(
        post_id,
        organization_id,
        with_publications=with_publications,
    )


async def refresh_post_rollups(db: AsyncSession, post: Post) -> None:
    """Совместимость со старым API: пересчитывает rollup-поля поста."""
    apply_post_rollups(post)


async def list_posts(db: AsyncSession, user: User) -> list[Post]:
    """Совместимость со старым API: делегирует список постов в PostService."""
    return await PostService(db).list_posts(user)


async def create_post(
    db: AsyncSession,
    user: User,
    title: str,
    text_draft: str,
    text_generated: str,
    tone: str,
    vk_post_id: str | None,
    strategy_id: str | None = None,
) -> Post:
    """Совместимость со старым API: делегирует создание поста в PostService."""
    return await PostService(db).create_post(
        user,
        title=title,
        text_draft=text_draft,
        text_generated=text_generated,
        tone=tone,
        vk_post_id=vk_post_id,
        strategy_id=strategy_id,
    )


async def update_post_vk(db: AsyncSession, post_id: str, user: User, vk_post_id: str | None) -> Post | None:
    """Совместимость со старым API: делегирует VK-обновление в PostService."""
    return await PostService(db).update_post_vk(post_id, user, vk_post_id)


async def update_post(
    db: AsyncSession,
    post_id: str,
    user: User,
    *,
    title: str | None = None,
    text_draft: str | None = None,
    text_generated: str | None = None,
    tone: str | None = None,
    strategy_id: str | None = None,
) -> Post | None:
    """Совместимость со старым API: делегирует обновление поста в PostService."""
    return await PostService(db).update_post(
        post_id,
        user,
        title=title,
        text_draft=text_draft,
        text_generated=text_generated,
        tone=tone,
        strategy_id=strategy_id,
    )


async def delete_post(db: AsyncSession, post_id: str, user: User) -> bool:
    """Совместимость со старым API: делегирует удаление поста в PostService."""
    return await PostService(db).delete_post(post_id, user)
