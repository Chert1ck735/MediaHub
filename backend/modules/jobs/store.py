"""Compatibility facade for background job storage and runner."""

from typing import Any

from backend.modules.jobs.container import background_job_runner, job_service
from backend.modules.jobs.interfaces import JobCoroutineFactory
from backend.modules.jobs.models import Job, JobCancelled, JobKind, JobStatus
from backend.modules.jobs.services.progress_reporter import ProgressReporter as _Reporter


async def create_job(kind: JobKind, *, message: str = "") -> Job:
    return await job_service.create_job(kind, message=message)


async def get_job(job_id: str) -> Job | None:
    return await job_service.get_job(job_id)


async def update_job(
    job_id: str,
    *,
    status: JobStatus | None = None,
    total: int | None = None,
    done: int | None = None,
    message: str | None = None,
) -> None:
    await job_service.update_job(
        job_id,
        status=status,
        total=total,
        done=done,
        message=message,
    )


def update_job_sync(
    job_id: str,
    *,
    total: int | None = None,
    done: int | None = None,
    message: str | None = None,
) -> None:
    job_service.update_job_sync(job_id, total=total, done=done, message=message)


async def finish_job(
    job_id: str,
    *,
    result: dict[str, Any] | None = None,
) -> None:
    await job_service.finish_job(job_id, result=result)


async def fail_job(job_id: str, *, error: str) -> None:
    await job_service.fail_job(job_id, error=error)


async def request_cancel(job_id: str) -> bool:
    return await job_service.request_cancel(job_id)


def is_cancelled(job_id: str) -> bool:
    return job_service.is_cancelled(job_id)


async def mark_cancelled(job_id: str) -> None:
    await job_service.mark_cancelled(job_id)


class ProgressReporter(_Reporter):
    def __init__(self, job_id: str) -> None:
        from backend.modules.jobs.container import job_repository

        super().__init__(job_id, job_repository)


def run_job_in_background(
    job: Job,
    coro_factory: JobCoroutineFactory,
):
    return background_job_runner.run(job, coro_factory)


__all__ = [
    "Job",
    "JobStatus",
    "JobKind",
    "JobCancelled",
    "ProgressReporter",
    "create_job",
    "get_job",
    "update_job",
    "update_job_sync",
    "finish_job",
    "fail_job",
    "request_cancel",
    "is_cancelled",
    "mark_cancelled",
    "run_job_in_background",
]
