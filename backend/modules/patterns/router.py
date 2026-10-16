"""HTTP layer for patterns."""

from fastapi import APIRouter, Depends, HTTPException, status

from backend.app.logger_config import get_logger
from backend.db.users import User
from backend.modules.auth.deps import get_current_user
from backend.modules.patterns.deps import get_module_service
from backend.modules.patterns.errors import ModuleError
from backend.modules.patterns.schemas import ModuleCreateRequest, ModuleResponse
from backend.modules.patterns.service import ModuleService

logger = get_logger(__name__)
router = APIRouter(prefix="/api/modules", tags=["modules"])


def _bad_request(exc: ModuleError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.get("", response_model=list[ModuleResponse])
async def get_modules(
    current_user: User = Depends(get_current_user),
    module_service: ModuleService = Depends(get_module_service),
) -> list[ModuleResponse]:
    logger.info(
        "Modules list requested",
        extra={
            "user_id": str(current_user.id),
            "endpoint": "GET /api/modules",
        },
    )

    try:
        modules = await module_service.list_modules(current_user)
    except ModuleError as exc:
        logger.warning(
            "Modules list rejected",
            extra={"user_id": str(current_user.id), "error": str(exc)},
        )
        raise _bad_request(exc) from exc

    logger.info(
        "Modules list built",
        extra={
            "user_id": str(current_user.id),
            "modules_count": len(modules),
        },
    )
    return [ModuleResponse.model_validate(module) for module in modules]


@router.post(
    "/create",
    response_model=ModuleResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_module(
    payload: ModuleCreateRequest,
    current_user: User = Depends(get_current_user),
    module_service: ModuleService = Depends(get_module_service),
) -> ModuleResponse:
    logger.info(
        "Module create requested",
        extra={
            "user_id": str(current_user.id),
            "module_name": payload.name,
        },
    )

    try:
        module, created = await module_service.create_or_update_module(
            current_user,
            name=payload.name,
            goal=payload.goal,
            description=payload.description,
        )
    except ModuleError as exc:
        logger.warning(
            "Module create rejected",
            extra={
                "user_id": str(current_user.id),
                "module_name": payload.name,
                "error": str(exc),
            },
        )
        raise _bad_request(exc) from exc
    except Exception as exc:
        logger.exception(
            "Module create failed unexpectedly",
            extra={
                "user_id": str(current_user.id),
                "module_name": payload.name,
                "error": str(exc),
            },
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        ) from exc

    logger.info(
        "Module saved",
        extra={
            "user_id": str(current_user.id),
            "module_id": str(module.id),
            "module_name": module.name,
            "module_created": created,
        },
    )
    return ModuleResponse.model_validate(module)
