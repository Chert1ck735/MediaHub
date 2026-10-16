from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class CreatePostRequest(BaseModel):
    message: str = Field(..., min_length=1, description="Текст поста")
    attachments: Optional[str] = Field(
        None, description="Вложения VK, например 'photo123_456'"
    )
    from_group: bool = Field(True, description="Публиковать от имени сообщества")

class CreatePostResponse(BaseModel):
    post_id: int
    url: str

class ParsePostsRequest(BaseModel):
    url: str = Field(
        ...,
        min_length=1,
        description=(
            "Ссылка на VK-сообщество. Поддерживается короткое имя ('svoedelomc'), "
            "'vk.com/<domain>', 'https://vk.com/<domain>', 'https://vk.com/club123', "
            "'https://vk.com/public123'."
        ),
    )
    max_posts: Optional[int] = Field(
        None, gt=0, description="Сколько постов выгрузить максимум."
    )

class ParsedPost(BaseModel):
    id: int
    date: datetime
    text: str
    likes: int
    reposts: int
    comments: int
    views: int


class ParsePostsResponse(BaseModel):
    domain: str
    count: int
    posts: list[ParsedPost]


class DeletePostRequest(BaseModel):
    post_id: int = Field(..., description="ID поста для удаления")


class DeletePostResponse(BaseModel):
    success: bool

class EditPostRequest(BaseModel):
    post_id: int = Field(..., description="ID поста VK для редактирования")
    message: str = Field(..., min_length=1, description="Новый текст поста")
    attachments: Optional[str] = Field(
        None, description="Вложения VK, например 'photo123_456'"
    )


class EditPostResponse(BaseModel):
    post_id: int
    url: str


class IngestVkLinkRequest(BaseModel):
    url: str = Field(
        ...,
        min_length=1,
        description=(
            "Любая ссылка VK: на сообщество (vk.com/mkotyukov), "
            "профиль (vk.com/id123 / vk.com/<screen>) или конкретный пост "
            "(vk.com/wall<owner>_<post>)."
        ),
    )
    max_posts: Optional[int] = Field(
        None, ge=1, description="Лимит постов; None/пусто — без лимита (вся стена)"
    )
    fetch_comments: bool = Field(
        True, description="Загружать комментарии к каждому посту"
    )
    date_from: Optional[datetime] = Field(
        None, description="Импортировать посты не старше этой даты (включительно)"
    )
    date_to: Optional[datetime] = Field(
        None, description="Импортировать посты не позже этой даты (включительно)"
    )


class IngestVkLinkResponse(BaseModel):
    type: str = Field(..., description="community | profile | post")
    canonical_url: str
    public_id: Optional[str] = None
    public_social_link_id: Optional[str] = None
    posts_imported: int = 0
    publications_imported: int = 0
    comments_imported: int = 0
    notes: Optional[list[str]] = None


class VkDefaultPublicResponse(BaseModel):
    public_social_link_id: Optional[str] = None
    title: Optional[str] = None
    url: Optional[str] = None
    external_public_id: Optional[str] = None
