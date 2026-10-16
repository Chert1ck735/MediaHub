"""Pydantic-схемы ответов автопарсера."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class AutoParseConfig(BaseModel):
    """Текущие настройки автопарсера (interval_hours — из БД, остальное .env)."""

    enabled: bool
    interval_hours: int
    lookback_days: int
    check_interval_seconds: int
    max_posts: int


class AutoParseConfigUpdate(BaseModel):
    """Изменение периода автопарсера администратором."""

    interval_hours: int = Field(
        ..., ge=1, le=24 * 30, description="Как часто проверять ссылки, в часах"
    )


class AutoParseLinkStatus(BaseModel):
    """Статус одной ссылки паблика для страницы проверки."""

    link_id: str
    network: str
    url: str
    public_id: str
    public_name: str
    last_autoparse_at: datetime | None
    is_due: bool


class AutoParseStatusResponse(BaseModel):
    config: AutoParseConfig
    links: list[AutoParseLinkStatus]


class AutoParseLinkResult(BaseModel):
    link_id: str
    network: str
    url: str
    public_id: str | None
    public_name: str | None
    checked: bool
    had_diff: bool
    parsed: bool
    posts_in_window: int
    real_comments: int
    stored_comments_before: int
    unparsed_estimate: int
    comments_imported: int
    skipped_reason: str | None
    error: str | None


class AutoParseRunResponse(BaseModel):
    started_at: str
    finished_at: str
    lookback_days: int
    links_total: int
    links_checked: int
    links_parsed: int
    comments_imported: int
    links: list[AutoParseLinkResult]
