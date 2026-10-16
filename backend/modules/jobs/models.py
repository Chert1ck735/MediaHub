from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class JobStatus(str, Enum):
    """
    Статусы фоновой задачи.

    Используется для отслеживания жизненного цикла долгой операции:
    от создания задачи до успешного завершения, ошибки или отмены пользователем.
    """

    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class JobKind(str, Enum):
    """
    Типы фоновых задач, которые поддерживает модуль jobs.

    Нужен, чтобы различать разные сценарии выполнения: например, импорт данных VK
    или Одноклассников и пересборку аналитического snapshot'а.
    """

    vk_ingest = "vk_ingest"
    ok_ingest = "ok_ingest"
    telegram_ingest = "telegram_ingest"
    analytics_rebuild = "analytics_rebuild"
    address_geocoding_backfill = "address_geocoding_backfill"
    vk_subscribers_refresh = "vk_subscribers_refresh"
    publics_import = "publics_import"


@dataclass
class Job:
    """
    Модель фоновой задачи в памяти приложения.

    Хранит состояние долгой операции: идентификатор, тип задачи, текущий статус,
    прогресс выполнения, служебное сообщение, результат, ошибку и флаг запроса
    отмены. В текущей реализации объект хранится в ``InMemoryJobRepository``, то
    есть после перезапуска приложения такие задачи не сохраняются.
    """

    id: str
    kind: JobKind
    status: JobStatus = JobStatus.pending
    total: int | None = None
    done: int = 0
    message: str = ""
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    finished_at: datetime | None = None
    result: dict[str, Any] | None = None
    error: str | None = None
    cancel_requested: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind.value,
            "status": self.status.value,
            "total": self.total,
            "done": self.done,
            "message": self.message,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "result": self.result,
            "error": self.error,
            "cancel_requested": self.cancel_requested,
        }


class JobCancelled(Exception):
    """Бросается фоновым воркером, когда пользователь отменил задачу."""
