"""Зависимости FastAPI для модуля авторизации."""

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.sentry import set_user_context
from backend.db.database import get_db
from backend.db.users import User
from backend.db.enums import UserStatus
from backend.modules.auth.services.auth_service import AuthService
from backend.modules.auth.services.token_service import TokenService

bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Возвращает текущего авторизованного пользователя по JWT-токену."""

    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Не авторизован",
        )

    token_service = TokenService()

    try:
        payload = token_service.decode_token(credentials.credentials)
        user_id = payload.get("sub")

        if not user_id:
            raise ValueError

    except (JWTError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Невалидный токен",
        )

    auth_service = AuthService(db)
    user = await auth_service.get_user_by_id(user_id)

    if not user or user.status != UserStatus.active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Пользователь не найден или доступ к учётной записи закрыт",
        )

    # Привязываем последующие ошибки этого запроса к пользователю и организации.
    # Без контекста событие в Sentry бесполезно: непонятно, у кого сломалось и в
    # какой организации. Пишем только id — почта и имя это персданные, а найти
    # человека по id в базе и так можно.
    set_user_context(
        user_id=str(user.id),
        organization_id=str(user.organization_id) if user.organization_id else None,
    )

    return user
