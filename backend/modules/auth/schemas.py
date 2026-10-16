"""Pydantic-схемы для модуля авторизации."""

from pydantic import BaseModel, Field


class RegisterRequest(BaseModel):
    """Схема запроса регистрации пользователя."""

    email: str = Field(..., min_length=3, max_length=255)
    name: str = Field(..., min_length=1, max_length=120)
    password: str = Field(..., min_length=6, max_length=200)


class LoginRequest(BaseModel):
    """Схема запроса входа пользователя."""

    email: str = Field(..., min_length=3, max_length=255)
    password: str = Field(..., min_length=1, max_length=200)


class SendCodeRequest(BaseModel):
    """Запрос кода подтверждения на почту."""

    email: str = Field(..., min_length=3, max_length=255)


class VerifyCodeRequest(BaseModel):
    """Проверка кода из письма.

    Ответ НИКОГДА не содержит сам код — он существует только в письме и в виде
    хеша в БД.
    """

    email: str = Field(..., min_length=3, max_length=255)
    code: str = Field(..., min_length=4, max_length=10)


class AcceptInvitationRequest(BaseModel):
    token: str = Field(..., min_length=20, max_length=200)
    password: str = Field(..., min_length=8, max_length=200)


class InvitationStatusRequest(BaseModel):
    token: str = Field(..., min_length=20, max_length=200)


class InvitationStatusResponse(BaseModel):
    status: str
    email: str | None = None
    message: str


class PasswordResetRequest(BaseModel):
    """Запрос кода для восстановления забытого пароля."""

    email: str = Field(..., min_length=3, max_length=255)


class PasswordResetConfirm(BaseModel):
    """Код из письма и новый пароль."""

    email: str = Field(..., min_length=3, max_length=255)
    code: str = Field(..., min_length=4, max_length=10)
    new_password: str = Field(..., min_length=8, max_length=200)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(..., min_length=1, max_length=200)
    new_password: str = Field(..., min_length=8, max_length=200)


class TokenResponse(BaseModel):
    """Схема ответа с access-токеном."""

    access_token: str
    token_type: str = "bearer"
    email: str
    name: str


class MeResponse(BaseModel):
    """Схема ответа с информацией о текущем пользователе."""

    id: str
    email: str
    name: str
    role: str
    # Фронту нужен для адресации ручек /api/organizations/{id}/... и для того,
    # чтобы решить, показывать ли раздел настроек.
    organization_id: str | None = None
    organization_name: str | None = None
    first_name: str = ""
    last_name: str = ""
