from typing import Any

from backend.modules.jobs.interfaces import JobRepository
from backend.modules.jobs.models import Job, JobKind, JobStatus


class JobService:
    """Прикладной сервис жизненного цикла фоновых задач."""

    def __init__(self, repository: JobRepository):
        self.repository = repository

    async def create_job(self, kind: JobKind, *, message: str = "") -> Job:
        return await self.repository.create(kind, message=message)

    async def get_job(self, job_id: str) -> Job | None:
        return await self.repository.get(job_id)

    async def update_job(
        self,
        job_id: str,
        *,
        status: JobStatus | None = None,
        total: int | None = None,
        done: int | None = None,
        message: str | None = None,
    ) -> None:
        await self.repository.update(
            job_id,
            status=status,
            total=total,
            done=done,
            message=message,
        )

    def update_job_sync(
        self,
        job_id: str,
        *,
        total: int | None = None,
        done: int | None = None,
        message: str | None = None,
    ) -> None:
        self.repository.update_sync(
            job_id,
            total=total,
            done=done,
            message=message,
        )

    async def finish_job(
        self,
        job_id: str,
        *,
        result: dict[str, Any] | None = None,
    ) -> None:
        await self.repository.finish(job_id, result=result)

    async def fail_job(self, job_id: str, *, error: str) -> None:
        await self.repository.fail(job_id, error=error)

    async def request_cancel(self, job_id: str) -> bool:
        return await self.repository.request_cancel(job_id)

    def is_cancelled(self, job_id: str) -> bool:
        return self.repository.is_cancelled(job_id)

    async def mark_cancelled(self, job_id: str) -> None:
        await self.repository.mark_cancelled(job_id)
