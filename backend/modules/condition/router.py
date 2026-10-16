from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status

from backend.app.config import settings
from backend.app.logger_config import get_logger
from backend.modules.condition.deps import get_condition_service
from backend.modules.condition.schema import AssessResponse, AssessRequest
from backend.modules.condition.services.condition_service import ConditionService

logger = get_logger(__name__)
router = APIRouter(prefix="/api/condition", tags=["condition"])


@router.post("/assess", response_model=AssessResponse)
def assess_condition(
    payload: AssessRequest,
    condition_service: ConditionService = Depends(get_condition_service),
) -> AssessResponse:
    csv_path = Path(payload.csv_path) if payload.csv_path else settings.vk_parser_output_abs

    logger.info(
        "Assess condition requested | csv_path=%s | window=%s",
        str(csv_path),
        payload.window,
    )

    if not csv_path.exists():
        logger.warning("Assess CSV not found | csv_path=%s", str(csv_path))
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"CSV not found: {csv_path}",
        )

    result = condition_service.assess(path=csv_path, window=payload.window)

    logger.info(
        "Assess completed | state=%s | avg_er=%s | sample_size=%s",
        result.state,
        result.avg_er,
        result.sample_size,
    )

    return AssessResponse(
        state=result.state,
        avg_er=result.avg_er,
        crisis_threshold=result.crisis_threshold,
        rise_threshold=result.rise_threshold,
        sample_size=result.sample_size,
    )
