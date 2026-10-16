import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from backend.modules.jobs.models import Job, JobKind, JobStatus


class InMemoryJobRepository:
    """Хранит фоновые задачи в памяти процесса."""

    def __init__(self, *, completed_ttl: timedelta = timedelta(hours=1)):
        self.completed_ttl = completed_ttl
        self._lock = asyncio.Lock()
        self._jobs: dict[str, Job] = {}

    def _gc_locked(self) -> None:
        now = datetime.now(timezone.utc)
        stale_ids = [
            job_id
            for job_id, job in self._jobs.items()
            if job.finished_at is not None
            and (now - job.finished_at) > self.completed_ttl
        ]
        for job_id in stale_ids:
            self._jobs.pop(job_id, None)

    async def create(self, kind: JobKind, *, message: str = "") -> Job:
        async with self._lock:
            self._gc_locked()
            job = Job(id=str(uuid.uuid4()), kind=kind, message=message)
            self._jobs[job.id] = job
            return job

    async def get(self, job_id: str) -> Job | None:
        async with self._lock:
            self._gc_locked()
            return self._jobs.get(job_id)

    async def update(
        self,
        job_id: str,
        *,
        status: JobStatus | None = None,
        total: int | None = None,
        done: int | None = None,
        message: str | None = None,
    ) -> None:
        async with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return
            if status is not None:
                job.status = status
            if total is not None:
                job.total = total
            if done is not None:
                job.done = done
            if message is not None:
                job.message = message

    def update_sync(
        self,
        job_id: str,
        *,
        total: int | None = None,
        done: int | None = None,
        message: str | None = None,
    ) -> None:
        job = self._jobs.get(job_id)
        if not job:
            return
        if total is not None:
            job.total = total
        if done is not None:
            job.done = done
        if message is not None:
            job.message = message

    async def increment(
        self,
        job_id: str,
        *,
        by: int = 1,
        message: str | None = None,
    ) -> None:
        async with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return
            job.done += by
            if message is not None:
                job.message = message

    async def finish(
        self,
        job_id: str,
        *,
        result: dict[str, Any] | None = None,
    ) -> None:
        async with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return
            job.status = JobStatus.completed
            job.result = result
            job.finished_at = datetime.now(timezone.utc)
            if job.total is not None:
                job.done = job.total

    async def fail(self, job_id: str, *, error: str) -> None:
        async with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return
            job.status = JobStatus.failed
            job.error = error
            job.finished_at = datetime.now(timezone.utc)

    async def request_cancel(self, job_id: str) -> bool:
        async with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return False
            if job.status in (
                JobStatus.completed,
                JobStatus.failed,
                JobStatus.cancelled,
            ):
                return False
            job.cancel_requested = True
            if not job.message.endswith("(cancel requested...)"):
                job.message = f"{job.message} (cancel requested...)".strip()
            return True

    def is_cancelled(self, job_id: str) -> bool:
        job = self._jobs.get(job_id)
        return bool(job and job.cancel_requested)

    async def mark_cancelled(self, job_id: str) -> None:
        async with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return
            job.status = JobStatus.cancelled
            job.finished_at = datetime.now(timezone.utc)
            if not job.error:
                job.error = "Cancelled by user"
