"""Пагинируемый список комментариев боли."""
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from backend.db import User
from backend.modules.analytics.repositories.comment_repository import CommentRepository
from backend.modules.analytics.repositories.pain_repository import PainRepository
from backend.modules.analytics.schemas import PainCommentsPage, PainCommentItem
from backend.modules.analytics.utils.comment_examples import vk_comment_url
from backend.modules.analytics.utils.public_link_filter import (
    compact_public_social_link_filter,
    parse_public_social_link_ids,
)
from backend.modules.analytics.utils.text_normalize import trim_text
from backend.modules.analytics.utils.time_helpers import period_to_since


class PainCommentsService:
    """Возвращает реальные комментарии, связанные с pain."""

    def __init__(
        self,
        db: AsyncSession,
        *,
        pain_repository: PainRepository | None = None,
        comment_repository: CommentRepository | None = None,
    ) -> None:
        self._db = db
        self._pain_repository = pain_repository or PainRepository(db)
        self._comment_repository = comment_repository or CommentRepository(db)

    async def list_comments(
        self,
        user: User,
        pain_id: str,
        *,
        subcategory: str | None = None,
        public_social_link_id: str | None = None,
        period: str = "all",
        municipality_name: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> PainCommentsPage:
        """Возвращает страницу комментариев по боли."""
        pain_uuid = uuid.UUID(pain_id)
        if await self._pain_repository.get_by_id(pain_id, user) is None:
            raise ValueError("Боль не найдена")

        link_ids = parse_public_social_link_ids(public_social_link_id)
        kwargs = {
            "pain_id": pain_uuid,
            "link_id": compact_public_social_link_filter(link_ids),
            "subcategory": subcategory,
            "since": period_to_since(period),
            "limit": limit,
            "offset": offset,
        }
        if municipality_name is not None:
            kwargs["municipality_name"] = municipality_name
        total, rows = await self._comment_repository.list_pain_comments_page(**kwargs)

        items: list[PainCommentItem] = []
        for row in rows:
            text = trim_text(str(row.text or ""), 500)
            if not text:
                continue
            official_response_id = getattr(row, "official_response_id", None)
            official_response_external_id = getattr(row, "official_response_external_id", None)
            official_response_url = (
                vk_comment_url(row.publication_url, official_response_external_id)
                if official_response_id
                else None
            )
            items.append(
                PainCommentItem(
                    comment_id=str(row.id),
                    text=text,
                    url=vk_comment_url(row.publication_url, row.external_id) or row.publication_url,
                    publication_url=row.publication_url,
                    sentiment=row.sentiment.value if row.sentiment else None,
                    message_type=row.message_type,
                    is_official_response=bool(row.is_official_response),
                    comment_date=row.comment_date.isoformat() if row.comment_date else None,
                    has_official_response=bool(official_response_id),
                    official_response_url=official_response_url,
                    official_response_text=(
                        trim_text(str(getattr(row, "official_response_text", "") or ""), 500)
                        if official_response_id
                        else None
                    ),
                    official_response_date=(
                        row.official_response_date.isoformat()
                        if official_response_id and row.official_response_date
                        else None
                    ),
                )
            )
        return PainCommentsPage(
            items=items,
            total=total,
            offset=offset,
            limit=limit,
            has_more=(offset + len(items)) < total,
        )
