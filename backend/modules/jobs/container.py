from backend.modules.jobs.repositories.in_memory_job_repository import (
    InMemoryJobRepository,
)
from backend.modules.jobs.services.background_job_runner import BackgroundJobRunner
from backend.modules.jobs.services.job_service import JobService


job_repository = InMemoryJobRepository()
job_service = JobService(job_repository)
background_job_runner = BackgroundJobRunner(job_repository)
