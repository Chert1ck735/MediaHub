"""HTTP-роуты для авторизации."""

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.logger_config import get_logger
from backend.db.database import get_db
from backend.db.organizations import Organization
from backend.db.users import User
from backend.modules.auth.deps import get_current_user
from backend.modules.auth.schemas import (
    LoginRequest,
    AcceptInvitationRequest,
    ChangePasswordRequest,
    InvitationStatusRequest,
    InvitationStatusResponse,
    MeResponse,
    PasswordResetConfirm,
    PasswordResetRequest,
    RegisterRequest,
    SendCodeRequest,
    TokenResponse,
    VerifyCodeRequest,
)
from backend.modules.auth.services.auth_service import AuthService
from backend.modules.auth.services.verification_service import VerificationService
from backend.modules.auth.services.invitation_service import InvitationService

logger = get_logger(__name__)
router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/invitations/accept", response_model=TokenResponse)
async def accept_invitation(
    payload: AcceptInvitationRequest,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    user, token = await InvitationService(db).accept(payload.token, payload.password)
    return TokenResponse(access_token=token, email=user.email, name=user.full_name)


@router.post("/invitations/status", response_model=InvitationStatusResponse)
async def invitation_status(
    payload: InvitationStatusRequest,
    db: AsyncSession = Depends(get_db),
) -> InvitationStatusResponse:
    result = await InvitationService(db).status(payload.token)
    return InvitationStatusResponse(**result)


@router.post("/send-code", status_code=status.HTTP_204_NO_CONTENT)
async def send_code(
    payload: SendCodeRequest,
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Отправляет код подтверждения на почту.

    В ответе кода НЕТ и быть не может: он существует только в письме. Раньше
    фронт генерировал код сам и показывал его на экране — это была не проверка,
    а её имитация.
    """
    # Сам email в лог не пишем целиком — это персональные данные.
    logger.info("Запрошен код подтверждения | domain=%s", payload.email.split("@")[-1])
    await VerificationService(db).send_code(payload.email)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/verify-code", status_code=status.HTTP_204_NO_CONTENT)
async def verify_code(
    payload: VerifyCodeRequest,
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Проверяет код из письма. 400 — не сошлось, 429 — слишком много попыток."""
    await VerificationService(db).verify_code(payload.email, payload.code)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/password-reset/request", status_code=status.HTTP_204_NO_CONTENT)
async def request_password_reset(
    payload: PasswordResetRequest,
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Отправляет код для смены забытого пароля.

    Отвечает 204 всегда, даже если такой почты нет: иначе форма становится
    способом узнать, кто зарегистрирован в системе.
    """
    logger.info(
        "Запрошен сброс пароля | domain=%s", payload.email.split("@")[-1]
    )
    await VerificationService(db).send_reset_code(payload.email)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/password-reset/confirm", status_code=status.HTTP_204_NO_CONTENT)
async def confirm_password_reset(
    payload: PasswordResetConfirm,
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Меняет пароль по коду из письма. 400 — код неверен или истёк."""
    await AuthService(db).reset_password(
        email=payload.email,
        code=payload.code,
        new_password=payload.new_password,
    )
    logger.info("Пароль изменён по коду | domain=%s", payload.email.split("@")[-1])
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/register",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
)
async def register(
    payload: RegisterRequest,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    """Регистрирует пользователя и возвращает access-токен."""

    logger.info(
        "Register attempt | email=%s | name=%s",
        payload.email,
        payload.name,
    )

    auth_service = AuthService(db)
    user, token = await auth_service.register(
        email=payload.email,
        name=payload.name,
        password=payload.password,
    )

    logger.info(
        "Register success | user_id=%s | email=%s",
        user.id,
        user.email,
    )

    return TokenResponse(
        access_token=token,
        email=user.email,
        name=user.full_name,
    )


@router.post("/login", response_model=TokenResponse)
async def login(
    payload: LoginRequest,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    """Авторизует пользователя и возвращает access-токен."""

    logger.info("Login attempt | email=%s", payload.email)

    auth_service = AuthService(db)
    result = await auth_service.authenticate(
        email=payload.email,
        password=payload.password,
    )

    if not result:
        logger.warning("Login failed | email=%s", payload.email)

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверная почта или пароль",
        )

    user, token = result

    logger.info(
        "Login success | user_id=%s | email=%s",
        user.id,
        user.email,
    )

    return TokenResponse(
        access_token=token,
        email=user.email,
        name=user.full_name,
    )

@router.get("/me", response_model=MeResponse)
async def me(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MeResponse:
    """Возвращает данные текущего пользователя."""

    logger.info("Me requested | user_id=%s", current_user.id)

    organization_name = None
    if current_user.organization_id:
        organization_name = await db.scalar(
            select(Organization.name).where(Organization.id == current_user.organization_id)
        )

    return MeResponse(
        id=str(current_user.id),
        email=current_user.email,
        name=current_user.full_name,
        role=current_user.role.value,
        organization_id=(
            str(current_user.organization_id) if current_user.organization_id else None
        ),
        organization_name=organization_name,
        first_name=current_user.first_name,
        last_name=current_user.last_name,
    )


@router.patch("/me/password", status_code=status.HTTP_204_NO_CONTENT)
async def change_my_password(
    payload: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    await AuthService(db).change_password(
        current_user,
        payload.current_password,
        payload.new_password,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
