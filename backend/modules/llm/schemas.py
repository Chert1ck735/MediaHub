from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator


class GeneratePostRequest(BaseModel):
    """Запрос на генерацию поста для выбранного официального паблика."""

    public_social_link_id: str = Field(
        min_length=1,
        description="Идентификатор паблика, для которого готовится пост",
    )
    event_description: str = Field(
        min_length=5,
        max_length=8_000,
        description="Обязательное описание инфоповода от пользователя",
    )
    event_date: date | None = Field(
        default=None,
        description="Необязательная дата события",
    )

    post_type: str | None = Field(
        default=None,
        description="Тип поста",
    )

    @field_validator("event_description")
    @classmethod
    def event_description_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 5:
            raise ValueError("event_description must contain at least 5 characters")
        return value


class GeneratePostResponse(BaseModel):
    """Ответ эндпоинта генерации поста."""

    text: str
    model: str


class CommentHierarchy(BaseModel):
    """Структурированный путь категории, присвоенный проанализированному комментарию."""

    category: str
    subcategory: str
    case: str


class CommentEntities(BaseModel):
    """Именованные сущности, извлеченные из комментария пользователя."""

    address: Optional[str] = None
    address_hierarchy: Optional[dict[str, Optional[str]]] = None
    institution: Optional[str] = None
    reference_number: Optional[str] = None
    deadline: Optional[str] = None


class CommentCandidate(BaseModel):
    """Альтернативная гипотеза категории с уверенностью модели."""

    category: str = ""
    subcategory: str = ""
    confidence: float = 0.0


class CommentAnalysisResponse(BaseModel):
    """Нормализованный результат классификации комментария языковой моделью.

    ``confidence`` и ``candidates`` имеют значения по умолчанию: модель может
    их не вернуть (старый промпт, провайдер без constrained decoding), и это
    не повод ронять разбор.
    """

    relevance: Literal["relevant", "irrelevant"]
    author_type: Literal["citizen", "admin", "official"]
    message_type: Literal["complaint", "request", "gratitude", "offtopic", "sarcasm"]
    sentiment: Literal["positive", "neutral", "negative"]
    is_official_response: bool
    hierarchy: CommentHierarchy
    entities: CommentEntities
    summary: str
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    candidates: list[CommentCandidate] = Field(default_factory=list)
