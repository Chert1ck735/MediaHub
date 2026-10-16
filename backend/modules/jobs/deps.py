from backend.modules.jobs.container import job_service
from backend.modules.jobs.services.job_service import JobService


def get_job_service() -> JobService:
    return job_service
