"""Контракты API настроек организации.

Это тот самый контракт, на который завязывается фронтенд. Валидируем на границе
один раз и внутрь пускаем уже типизированное — сервисы не перепроверяют формат
email заново.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.db.enums import (
    AccessResourceType,
    AccessSubjectType,
    OrgType,
    PermissionEnum,
    UserRole,
    UserStatus,
)

# Свой формат вместо pydantic EmailStr: тот тянет зависимость email-validator,
# которой в проекте нет, а остальные схемы (auth) и так живут на обычном str.
# Строгая валидность всё равно подтверждается только доставкой письма.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _normalize_email(value: str) -> str:
    """Нормализует и проверяет email.

    Приведение к lowercase обязательно: в БД стоит CHECK
    (ck_users_email_lowercase), и адрес с заглавными буквами упал бы на
    констрейнте уже в глубине драйвера, а не внятной 422 на границе.
    """
    email = value.strip().lower()
    if not _EMAIL_RE.match(email):
        raise ValueError("Некорректный email")
    return email


# ── организации ─────────────────────────────────────────────────────────────

class OrganizationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    type: OrgType
    description: str | None = None
    region_id: uuid.UUID | None = None
    region_name: str | None = None
    municipality_name: str | None = None
    is_active: bool
    created_at: datetime
    user_count: int = 0
    community_count: int = 0


class OrganizationCreateRequest(BaseModel):
    """Заведение организации. Заодно можно сразу создать её администратора —
    организация без админа управляема только суперадмином и потому бесполезна."""

    name: str = Field(..., min_length=1, max_length=255)
    type: OrgType = OrgType.government
    description: str | None = Field(default=None, max_length=2000)
    region_id: uuid.UUID | None = None
    municipality_name: str | None = Field(default=None, max_length=255)

    admin_email: str | None = Field(default=None, max_length=255)
    admin_first_name: str | None = Field(default=None, max_length=120)
    admin_last_name: str | None = Field(default=None, max_length=120)

    @field_validator("admin_email")
    @classmethod
    def _check_admin_email(cls, v: str | None) -> str | None:
        return _normalize_email(v) if v else None


class OrganizationUpdateRequest(BaseModel):
    """None = «не трогать поле»."""

    name: str | None = Field(default=None, min_length=1, max_length=255)
    type: OrgType | None = None
    description: str | None = Field(default=None, max_length=2000)
    region_id: uuid.UUID | None = None
    municipality_name: str | None = Field(default=None, max_length=255)
    is_active: bool | None = None


# ── пользователи ────────────────────────────────────────────────────────────

class UserGroupBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    first_name: str
    last_name: str
    full_name: str
    role: UserRole
    status: UserStatus
    created_at: datetime
    groups: list[UserGroupBrief] = Field(default_factory=list)
    # Сколько сообществ реально доступно с учётом групп — колонка в таблице UI.
    accessible_communities_count: int = 0


class UserListResponse(BaseModel):
    items: list[UserResponse]
    total: int
    page: int
    page_size: int


class UserCreateRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=255)
    first_name: str = Field(..., min_length=1, max_length=120)
    last_name: str = Field(default="", max_length=120)
    role: UserRole = UserRole.minion
    group_ids: list[uuid.UUID] = Field(default_factory=list)

    @field_validator("email")
    @classmethod
    def _check_email(cls, v: str) -> str:
        return _normalize_email(v)


class UserUpdateRequest(BaseModel):
    """Частичное обновление: None = «не трогать это поле».

    Отличать «не передали» от «передали пустое» обязательно, иначе PATCH без
    группы молча вычистит все группы пользователя.
    """

    email: str | None = Field(default=None, min_length=3, max_length=255)
    first_name: str | None = Field(default=None, min_length=1, max_length=120)
    last_name: str | None = Field(default=None, max_length=120)
    role: UserRole | None = None
    status: UserStatus | None = None
    group_ids: list[uuid.UUID] | None = None

    @field_validator("email")
    @classmethod
    def _check_email(cls, v: str | None) -> str | None:
        return _normalize_email(v) if v else v


class EffectiveAccessItem(BaseModel):
    """Право с источником: выдано лично или унаследовано через группу."""

    community_id: uuid.UUID
    community_name: str
    permission: PermissionEnum
    source_type: Literal["direct", "user_group"]
    source_name: str | None = None


# ── группы пользователей ────────────────────────────────────────────────────

class UserGroupResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str | None = None
    created_at: datetime
    member_count: int = 0
    grant_count: int = 0


class UserGroupWriteRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    member_ids: list[uuid.UUID] = Field(default_factory=list)


# ── группы сообществ ────────────────────────────────────────────────────────

class CommunityGroupResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str | None = None
    created_at: datetime
    community_count: int = 0
    grant_count: int = 0


class CommunityGroupWriteRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    community_ids: list[uuid.UUID] = Field(default_factory=list)


class CommunityBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str


# ── права ───────────────────────────────────────────────────────────────────

class DataHealthThresholds(BaseModel):
    fresh_hours: int
    warning_hours: int


class DataHealthSummary(BaseModel):
    links_count: int
    active_links_count: int
    posts_count: int
    comments_count: int
    classified_count: int
    pending_count: int
    processing_count: int
    failed_count: int
    missing_analysis_count: int
    classification_percent: float
    stale_links_count: int
    warning_links_count: int
    incomplete_classification_links_count: int
    failed_classification_links_count: int
    oldest_data_age_hours: float | None = None


class DataHealthItem(BaseModel):
    public_id: uuid.UUID
    public_name: str
    link_id: uuid.UUID
    link_title: str | None = None
    url: str
    is_active: bool
    social_network_code: str
    social_network_name: str
    posts_count: int
    comments_count: int
    analyzed_count: int
    classified_count: int
    pending_count: int
    processing_count: int
    failed_count: int
    missing_analysis_count: int
    classification_percent: float
    last_publication_at: datetime | None = None
    last_post_sync_at: datetime | None = None
    last_comment_at: datetime | None = None
    last_parsed_at: datetime | None = None
    last_analysis_at: datetime | None = None
    data_age_hours: float | None = None
    data_status: Literal["empty", "fresh", "warning", "stale", "unknown"]
    classification_status: Literal[
        "no_comments",
        "complete",
        "processing",
        "incomplete",
        "has_errors",
    ]
    overall_status: Literal[
        "ok",
        "attention",
        "stale_data",
        "classification_incomplete",
        "classification_errors",
        "empty",
    ]


class DataHealthResponse(BaseModel):
    generated_at: datetime
    thresholds: DataHealthThresholds
    summary: DataHealthSummary
    items: list[DataHealthItem] = Field(default_factory=list)


class GrantItem(BaseModel):
    resource_type: AccessResourceType
    resource_id: uuid.UUID
    permission: PermissionEnum


class GrantMatrixResponse(BaseModel):
    """Матрица прав субъекта — то, что рисуют чекбоксами."""

    subject_type: AccessSubjectType
    subject_id: uuid.UUID
    grants: list[GrantItem]


class GrantReplaceRequest(BaseModel):
    """Полная замена набора грантов субъекта.

    Именно replace, а не add/remove: UI редактирует матрицу целиком, и
    инкрементальные операции разъезжаются с ней при гонке двух вкладок.
    """

    subject_type: AccessSubjectType
    subject_id: uuid.UUID
    grants: list[GrantItem]


# ── импорт ──────────────────────────────────────────────────────────────────

ImportRowStatus = Literal["create", "update", "skip", "error"]


class ImportRowPreview(BaseModel):
    row_number: int
    status: ImportRowStatus
    email: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    role: UserRole | None = None
    user_groups: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ImportPreviewResponse(BaseModel):
    rows: list[ImportRowPreview]
    to_create: int
    to_update: int
    skipped: int
    errors: int
    # Группы, которых ещё нет и которые будут созданы при подтверждении.
    new_groups: list[str] = Field(default_factory=list)


class ImportConfirmRequest(BaseModel):
    """Подтверждаются строки, вернувшиеся из preview.

    Клиент присылает их обратно, а не ссылку на серверный кэш: preview
    stateless, и подтверждение не протухает между шагами wizard'а.
    """

    rows: list[ImportRowPreview]


class ImportResultResponse(BaseModel):
    created: int
    updated: int
    skipped: int
    errors: int
    created_groups: list[str] = Field(default_factory=list)
    error_rows: list[ImportRowPreview] = Field(default_factory=list)


# ── импорт площадок ────────────────────────────────────────────────────────

PublicImportRowStatus = Literal["create", "skip", "error"]


class PublicImportRowPreview(BaseModel):
    """Превью одной строки импорта площадок."""

    row_number: int
    status: PublicImportRowStatus
    name: str | None = None
    url: str | None = None
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class PublicImportPreviewResponse(BaseModel):
    rows: list[PublicImportRowPreview]
    to_create: int
    skipped: int
    errors: int


class PublicImportConfirmRequest(BaseModel):
    rows: list[PublicImportRowPreview]
    # Период истории — тот же, что у ручного добавления ссылки.
    date_from: datetime | None = None
    date_to: datetime | None = None


class PublicImportJobResponse(BaseModel):
    """Импорт запущен фоновой задачей — по job_id фронт следит за прогрессом."""

    job_id: str


class PublicImportResultResponse(BaseModel):
    created: int
    skipped: int
    errors: int
    error_rows: list[PublicImportRowPreview] = Field(default_factory=list)
