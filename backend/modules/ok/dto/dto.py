"""DTO OK-модуля: структуры передачи данных между слоями."""

from dataclasses import dataclass, field
from enum import Enum


class OkLinkType(str, Enum):
    """Тип ссылки Одноклассников."""

    GROUP = "group"
    PROFILE = "profile"
    TOPIC = "topic"


@dataclass(frozen=True)
class OkLinkRef:
    """Нормализованное описание OK-ссылки.

    ``group_ref`` — то, что стоит в URL: числовой uid группы либо shortname.
    Числовой id появляется только после group.getInfo.
    """

    type: OkLinkType
    raw_url: str
    canonical_url: str
    group_ref: str | None = None
    group_id: str | None = None
    profile_ref: str | None = None
    topic_id: str | None = None


@dataclass(frozen=True)
class OkOwnerInfoDTO:
    """DTO нормализованного владельца OK-стены (группы)."""

    name: str
    description: str | None
    shortname: str
    canonical_url: str
    external_public_id: str
    group_id: str
    members_count: int = 0


@dataclass(frozen=True)
class OkTopicStatsDTO:
    """Агрегаты темы из group.getStatTopics."""

    topic_id: str
    likes: int = 0
    comments: int = 0
    reshares: int = 0
    views: int = 0


@dataclass(frozen=True)
class OkIngestResult:
    """DTO результата импорта OK-ссылки."""

    type: OkLinkType
    canonical_url: str
    public_id: str | None
    public_social_link_id: str | None
    posts_imported: int = 0
    comments_imported: int = 0
    publications_imported: int = 0
    notes: list[str] | None = field(default=None)
