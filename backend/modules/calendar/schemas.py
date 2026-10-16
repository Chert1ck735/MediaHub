from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, Field


class EventCreateRequest(BaseModel):
    title: str
    date: str
    description: str = ""
    start_time: str = "10:00"
    end_time: str = "11:00"
    status: str = "scheduled"
    platforms: Annotated[list[str], Field(default_factory=lambda: ["VK"])]
    public_social_link_ids: list[str] = Field(default_factory=list)
    draft: str = ""
    tone: str = ""
    post_type: str = ""
    post_id: str | None = None
    info_event_id: str | None = None


class EventResponse(BaseModel):
    id: str
    title: str
    origin: str | None = None
    date: str
    start_time: str
    end_time: str
    description: str
    status: str
    platforms: list[str]
    draft: str
    tone: str
    post_type: str
    post_id: str | None = None
    info_event_id: str | None = None
    info_event_title: str | None = None
    inherited_pain_ids: list[str] = Field(default_factory=list)
    inherited_pain_titles: list[str] = Field(default_factory=list)
    publication_ids: list[str] = Field(default_factory=list)
    public_social_link_ids: list[str] = Field(default_factory=list)
    publication_urls: list[str | None] = Field(default_factory=list)
    # Всего публикаций в этом дне: в ответе их только несколько на день,
    # а под ячейкой надо показать «+N ещё».
    day_total: int = 0
