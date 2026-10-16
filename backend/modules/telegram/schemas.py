from datetime import datetime

from pydantic import BaseModel, Field


class IngestTelegramLinkRequest(BaseModel):
    url: str = Field(
        ...,
        min_length=1,
        description="Публичная ссылка Telegram: t.me/<канал> или t.me/<канал>/<пост>",
    )
    max_posts: int | None = Field(None, ge=1, description="Максимум постов за один импорт")
    fetch_comments: bool = Field(True, description="Загружать комментарии из discussion-группы")
    date_from: datetime | None = None
    date_to: datetime | None = None


class IngestTelegramLinkResponse(BaseModel):
    type: str = "channel"
    canonical_url: str
    public_id: str | None = None
    public_social_link_id: str | None = None
    posts_imported: int = 0
    publications_imported: int = 0
    comments_imported: int = 0
    notes: list[str] | None = None

