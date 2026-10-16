from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class IngestOkLinkRequest(BaseModel):
    url: str = Field(
        ...,
        min_length=1,
        description=(
            "Ссылка Одноклассников: на группу (ok.ru/group/<id|shortname>), "
            "на короткое имя (ok.ru/<shortname>) или на конкретную тему "
            "(ok.ru/group/<id>/topic/<topic_id>). Профили не поддерживаются."
        ),
    )
    max_posts: Optional[int] = Field(
        None, ge=1, description="Лимит тем; None/пусто — без лимита (вся лента)"
    )
    fetch_comments: bool = Field(True, description="Загружать комментарии к каждой теме")
    date_from: Optional[datetime] = Field(
        None, description="Импортировать темы не старше этой даты (включительно)"
    )
    date_to: Optional[datetime] = Field(
        None, description="Импортировать темы не позже этой даты (включительно)"
    )


class IngestOkLinkResponse(BaseModel):
    type: str = Field(..., description="group | topic")
    canonical_url: str
    public_id: Optional[str] = None
    public_social_link_id: Optional[str] = None
    posts_imported: int = 0
    publications_imported: int = 0
    comments_imported: int = 0
    notes: Optional[list[str]] = None


class ResolveOkLinkResponse(BaseModel):
    """Результат разбора OK-ссылки без обращения к API."""

    type: str = Field(..., description="group | profile | topic")
    canonical_url: str
    group_ref: Optional[str] = None
    topic_id: Optional[str] = None
    profile_ref: Optional[str] = None
    supported: bool = Field(..., description="Поддерживается ли импорт такой ссылки")
