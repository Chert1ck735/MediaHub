from typing import Any, Awaitable, Callable, Protocol

from backend.modules.jobs.models import Job, JobKind, JobStatus


class JobRepository(Protocol):
    async def create(self, kind: JobKind, *, message: str = "") -> Job:
        ...

    async def get(self, job_id: str) -> Job | None:
        ...

    async def update(
        self,
        job_id: str,
        *,
        status: JobStatus | None = None,
        total: int | None = None,
        done: int | None = None,
        message: str | None = None,
    ) -> None:
        ...

    def update_sync(
        self,
        job_id: str,
        *,
        total: int | None = None,
        done: int | None = None,
        message: str | None = None,
    ) -> None:
        ...

    async def increment(
        self,
        job_id: str,
        *,
        by: int = 1,
        message: str | None = None,
    ) -> None:
        ...

    async def finish(
        self,
        job_id: str,
        *,
        result: dict[str, Any] | None = None,
    ) -> None:
        ...

    async def fail(self, job_id: str, *, error: str) -> None:
        ...

    async def request_cancel(self, job_id: str) -> bool:
        ...

    def is_cancelled(self, job_id: str) -> bool:
        ...

    async def mark_cancelled(self, job_id: str) -> None:
        ...


class ProgressReporterProtocol(Protocol):
    async def update(
        self,
        *,
        total: int | None = None,
        done: int | None = None,
        message: str | None = None,
    ) -> None:
        ...

    async def inc(self, *, by: int = 1, message: str | None = None) -> None:
        ...

    def update_sync(
        self,
        *,
        total: int | None = None,
        done: int | None = None,
        message: str | None = None,
    ) -> None:
        ...

    def is_cancelled(self) -> bool:
        ...

    def raise_if_cancelled(self) -> None:
        ...


JobCoroutineFactory = Callable[
    [ProgressReporterProtocol],
    Awaitable[dict[str, Any] | None],
]
