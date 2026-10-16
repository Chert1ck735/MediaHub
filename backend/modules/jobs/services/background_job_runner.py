import asyncio
import logging

from backend.app.sentry import capture
from backend.modules.jobs.interfaces import JobCoroutineFactory, JobRepository
from backend.modules.jobs.models import Job, JobCancelled, JobStatus
from backend.modules.jobs.services.progress_reporter import ProgressReporter

logger = logging.getLogger(__name__)


class BackgroundJobRunner:
    """Выполняет фоновые задачи и обновляет их статус."""

    def __init__(self, repository: JobRepository):
        self.repository = repository

    def run(
        self,
        job: Job,
        coro_factory: JobCoroutineFactory,
    ) -> asyncio.Task:
        async def runner() -> None:
            progress = ProgressReporter(job.id, self.repository)
            await self.repository.update(job.id, status=JobStatus.running)
            try:
                result = await coro_factory(progress)
                await self.repository.finish(job.id, result=result)
            except JobCancelled:
                logger.info("Background job %s (%s) cancelled", job.id, job.kind.value)
                await self.repository.mark_cancelled(job.id)
            except Exception as exc:
                # Задача живёт в отдельной asyncio-таске: HTTP-обработчик
                # исключений до неё не дотягивается, и без явной отправки падение
                # фоновой пересборки/ингеста не увидел бы никто, кроме лога.
                capture(
                    exc,
                    job_id=job.id,
                    job_kind=job.kind.value,
                )
                logger.exception(
                    "Background job %s (%s) failed",
                    job.id,
                    job.kind.value,
                )
                await self.repository.fail(job.id, error=str(exc))

        return asyncio.create_task(runner(), name=f"job-{job.kind.value}-{job.id[:8]}")
