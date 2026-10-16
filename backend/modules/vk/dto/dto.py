"""DTO VK-модуля: структуры передачи данных между слоями."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any


class VkLinkType(str, Enum):
    """Тип VK-ссылки."""

    COMMUNITY = "community"
    PROFILE = "profile"
    POST = "post"


@dataclass(frozen=True)
class VkApiRequest:
    """DTO запроса к методу VK API."""

    method: str
    params: dict[str, Any]


@dataclass(frozen=True)
class ParsedVkPostDTO:
    """DTO распарсенного поста для ответа /parse и CSV-экспорта."""

    id: int | None
    date: datetime
    text: str
    likes: int
    reposts: int
    comments: int
    views: int


@dataclass(frozen=True)
class FetchPostsResultDTO:
    """DTO результата загрузки постов со стены."""

    posts: list[dict[str, Any]]
    domain_label: str


@dataclass(frozen=True)
class CreateVkPostDTO:
    """DTO команды публикации поста."""

    message: str
    attachments: str | None = None
    from_group: bool = True
    owner_id: int | None = None
    publish_date: datetime | int | None = None


@dataclass(frozen=True)
class EditVkPostDTO:
    """DTO команды редактирования поста."""

    post_id: int
    message: str
    attachments: str | None = None
    owner_id: int | None = None
    publish_date: datetime | int | None = None


@dataclass(frozen=True)
class UploadPhotoDTO:
    """DTO команды загрузки фото на стену VK."""

    file_bytes: bytes
    filename: str
    content_type: str


@dataclass(frozen=True)
class CsvExportDTO:
    """DTO команды сохранения постов в CSV."""

    posts: list[dict[str, Any]]
    filename: Path | None = None


@dataclass(frozen=True)
class IngestResult:
    """DTO результата импорта VK-ссылки."""

    type: VkLinkType
    canonical_url: str
    public_id: str | None
    public_social_link_id: str | None
    posts_imported: int = 0
    comments_imported: int = 0
    publications_imported: int = 0
    notes: list[str] | None = field(default=None)


@dataclass(frozen=True)
class VkOwnerInfoDTO:
    """DTO нормализованного владельца VK-стены."""

    name: str
    description: str | None
    screen: str
    canonical_url: str
    external_public_id: str
    owner_id: int
    members_count: int = 0
    is_closed: bool = False
    can_access_closed: bool = True


@dataclass(frozen=True)
class VkLinkRef:
    """Нормализованное описание VK-ссылки."""

    type: VkLinkType
    raw_url: str
    canonical_url: str
    domain: str | None = None
    owner_id: int | None = None
    post_id: int | None = None
    screen_name: str | None = None
