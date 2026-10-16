import enum


class UserRole(str, enum.Enum):
    """Роли пользователей.

    Роль задаёт организационные возможности и НЕ выдаёт доступ к сообществам:
    доступ к конкретным сообществам живёт в ``access_grants`` (кроме superadmin,
    который проходит любую проверку).

    * ``superadmin`` — все организации, назначает администраторов;
    * ``admin`` — только своя организация: пользователи, группы, права;
    * ``minion`` — рядовой пользователь, видит только выданные ему сообщества.
    """

    superadmin = "superadmin"
    admin = "admin"
    minion = "minion"


class UserStatus(str, enum.Enum):
    """Статус пользователя.

    ``invited`` — создан, но приглашение ещё не принято.
    ``blocked`` — доступ отозван, но пользователь и его гранты сохранены.
    """

    active = "active"
    blocked = "blocked"
    invited = "invited"


class PermissionEnum(str, enum.Enum):
    """Коды прав, выдаваемых на сообщество или группу сообществ."""

    view_community = "view_community"
    create_post = "create_post"
    # Резерв: управление сообществом и сводная аналитика организации.
    manage_community = "manage_community"
    view_organization_analytics = "view_organization_analytics"


class AccessSubjectType(str, enum.Enum):
    """Кому выдан грант."""

    user = "user"
    user_group = "user_group"


class AccessResourceType(str, enum.Enum):
    """На что выдан грант. ``community`` — это ``publics.id``."""

    community = "community"
    community_group = "community_group"

class OrgType(str, enum.Enum):
    """
    Типы организаций
    """

    government = "government"
    university = "university"
    volunteer = "volunteer"
    business = "business"
    other = "other"
    youth_center = "youth_center"


class PostType(str, enum.Enum):
    event_announcement = "event_announcement"
    event_result = "event_result"
    vacancy = "vacancy"
    grant = "grant"
    news = "news"
    poll = "poll"
    other = "other"


class PostStatus(str, enum.Enum):
    draft = "draft"
    scheduled = "scheduled"
    published = "published"


class ModuleType(str, enum.Enum):
    events = "events"
    volunteer = "volunteer"


class Platform(str, enum.Enum):
    vk = "vk"
    telegram = "telegram"
    dzen = "dzen"
    ok = "ok"
    youtube = "youtube"


class PostOriginEnum(str, enum.Enum):
    parsed = "parsed"
    manual = "manual"
    llm_generated = "llm_generated"


class PublicationStatusEnum(str, enum.Enum):
    pending = "pending"
    scheduled = "scheduled"
    published = "published"
    error = "error"
    deleted = "deleted"


class ContentTypeEnum(str, enum.Enum):
    text = "text"
    photo = "photo"
    video = "video"
    mixed = "mixed"
    poll = "poll"
    document = "document"
    other = "other"


class EventSource(str, enum.Enum):
    google_calendar = "google_calendar"
    manual = "manual"


class SourceTypeEnum(str, enum.Enum):
    api = "api"
    excel = "excel"
    manual = "manual"


class SystemStateEnum(str, enum.Enum):
    normal = "normal"
    growth = "growth"
    crisis = "crisis"


class SentimentEnum(str, enum.Enum):
    positive = "positive"
    neutral = "neutral"
    negative = "negative"


class RelevanceEnum(str, enum.Enum):
    relevant = "relevant"
    irrelevant = "irrelevant"


class PainStatusEnum(str, enum.Enum):
    active = "active"
    in_progress = "in_progress"
    resolved = "resolved"


class SeverityLevelEnum(str, enum.Enum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


class MetricPeriodEnum(str, enum.Enum):
    day = "day"
    week = "week"
    month = "month"
