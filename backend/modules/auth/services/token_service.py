"""Сервис для создания и декодирования JWT-токенов."""

from datetime import datetime, timezone, timedelta

from jose import jwt

from backend.app.config import settings


class TokenService:
    """Отвечает только за работу с JWT-токенами."""

    def create_access_token(self, user_id: str, email: str) -> str:
        """Создаёт access-токен пользователя."""

        expire = datetime.now(timezone.utc) + timedelta(days=settings.JWT_EXPIRE_DAYS)

        return jwt.encode(
            {
                "sub": user_id,
                "email": email,
                "exp": expire,
            },
            settings.JWT_SECRET,
            algorithm=settings.JWT_ALGORITHM,
        )

    def decode_token(self, token: str) -> dict:
        """Декодирует JWT-токен и возвращает payload."""

        return jwt.decode(
            token,
            settings.JWT_SECRET,
            algorithms=[settings.JWT_ALGORITHM],
        )
