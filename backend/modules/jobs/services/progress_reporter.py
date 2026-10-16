from backend.modules.jobs.interfaces import JobRepository
from backend.modules.jobs.models import JobCancelled


class ProgressReporter:
    """Фасад для обновления прогресса из долгих задач."""

    def __init__(self, job_id: str, repository: JobRepository) -> None:
        self.job_id = job_id
        self.repository = repository

    def is_cancelled(self) -> bool:
        return self.repository.is_cancelled(self.job_id)

    def raise_if_cancelled(self) -> None:
        """Прерывает задачу, если пользователь нажал «Отменить»."""
        if self.repository.is_cancelled(self.job_id):
            raise JobCancelled()

    async def update(
        self,
        *,
        total: int | None = None,
        done: int | None = None,
        message: str | None = None,
    ) -> None:
        await self.repository.update(
            self.job_id,
            total=total,
            done=done,
            message=message,
        )

    async def inc(self, *, by: int = 1, message: str | None = None) -> None:
        await self.repository.increment(self.job_id, by=by, message=message)

    def update_sync(
        self,
        *,
        total: int | None = None,
        done: int | None = None,
        message: str | None = None,
    ) -> None:
        """Синхронный апдейт для прогресса из блокирующего кода (VK-пагинация)."""
        self.repository.update_sync(
            self.job_id,
            total=total,
            done=done,
            message=message,
        )
