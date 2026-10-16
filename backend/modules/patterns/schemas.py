"""Pydantic-схемы HTTP-контракта patterns."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ModuleCreateRequest(BaseModel):
    """Тело запроса на создание или обновление модуля."""

    name: str
    goal: str | None = None
    description: str | None = None


class ModuleResponse(BaseModel):
    """Ответ API с сохраненным модулем и его configuration."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    public_id: uuid.UUID
    name: str
    goal: str | None
    description: str | None
    configuration: dict
    created_at: datetime
    updated_at: datetime
