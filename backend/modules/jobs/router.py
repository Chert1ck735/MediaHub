"""HTTP layer for background jobs."""

from fastapi import APIRouter, Depends, HTTPException, status

from backend.db.users import User
from backend.modules.auth.deps import get_current_user
from backend.modules.jobs.deps import get_job_service
from backend.modules.jobs.services.job_service import JobService

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.get("/{job_id}")
async def get_job_status(
    job_id: str,
    _: User = Depends(get_current_user),
    job_service: JobService = Depends(get_job_service),
) -> dict:
    job = await job_service.get_job(job_id)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job not found",
        )
    return job.to_dict()


@router.post("/{job_id}/cancel")
async def cancel_job_route(
    job_id: str,
    _: User = Depends(get_current_user),
    job_service: JobService = Depends(get_job_service),
) -> dict:
    ok = await job_service.request_cancel(job_id)
    if not ok:
        job = await job_service.get_job(job_id)
        if not job:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Job not found",
            )
        return {"ok": False, "status": job.status.value}
    return {"ok": True}
