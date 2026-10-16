"""Выдача, повторная отправка и принятие приглашений."""
from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode
from urllib.parse import urlsplit, urlunsplit

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.config import settings
from backend.db.enums import UserStatus
from backend.db.invitations import Invitation
from backend.db.users import User
from backend.modules.auth.services import email_service
from backend.modules.auth.services.password_service import PasswordService
from backend.modules.auth.services.token_service import TokenService

logger = logging.getLogger(__name__)


class InvitationService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._passwords = PasswordService()
        self._tokens = TokenService()

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _hash_token(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    @staticmethod
    def _url(token: str, public_base_url: str | None = None) -> str:
        configured_base = settings.APP_PUBLIC_URL.strip()
        base = configured_base or (public_base_url or "").strip()
        # Прямые вызовы сервиса в dev (тесты/консоль) не имеют HTTP Origin.
        # Роуты всегда передают реальный адрес браузера, поэтому в письмах из
        # интерфейса этот fallback не используется.
        if not base and settings.APP_ENV.lower() != "prod":
            base = "http://localhost:5173"

        parsed = urlsplit(base)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username:
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "Не настроен публичный адрес приложения для приглашений.",
            )

        # Origin из заголовка запроса нельзя слепо доверять на prod: иначе
        # обладатель админского JWT подставит свой домен, и токен утечёт ему
        # при клике получателя. Разрешаем только origin из CORS allowlist.
        normalized_base = urlunsplit((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", ""))
        if not configured_base and settings.APP_ENV.lower() == "prod":
            allowed = {
                item.strip().rstrip("/")
                for item in settings.CORS_ALLOWED_ORIGINS.split(",")
                if item.strip()
            }
            if normalized_base not in allowed:
                raise HTTPException(
                    status.HTTP_503_SERVICE_UNAVAILABLE,
                    "Адрес сайта не разрешён для ссылок-приглашений.",
                )

        return f"{normalized_base}/?{urlencode({'invite': token})}"

    async def _record_for_user(self, user_id) -> Invitation | None:
        return await self._db.scalar(
            select(Invitation).where(Invitation.user_id == user_id).with_for_update()
        )

    async def issue(
        self,
        user: User,
        *,
        invited_by=None,
        enforce_cooldown: bool = False,
        public_base_url: str | None = None,
    ) -> None:
        """Выдаёт новый токен и отправляет письмо атомарно с изменениями БД.

        SMTP вызывается до коммита. Так API не отвечает ошибкой после того,
        как пользователь уже создан, а повторная отправка при сбое не гасит
        прежнюю рабочую ссылку.
        """
        if user.status != UserStatus.invited:
            raise HTTPException(status.HTTP_409_CONFLICT, "Пользователь уже активирован")

        now = self._now()
        record = await self._record_for_user(user.id)
        if record is not None and enforce_cooldown:
            elapsed = (now - record.last_sent_at).total_seconds()
            cooldown = settings.INVITATION_RESEND_COOLDOWN_SECONDS
            if elapsed < cooldown:
                raise HTTPException(
                    status.HTTP_429_TOO_MANY_REQUESTS,
                    f"Повторно отправить приглашение можно через {int(cooldown - elapsed)} с",
                )

        token = secrets.token_urlsafe(32)
        if record is None:
            record = Invitation(user_id=user.id)
            self._db.add(record)
        record.token_hash = self._hash_token(token)
        record.expires_at = now + timedelta(hours=settings.INVITATION_TTL_HOURS)
        record.last_sent_at = now
        record.invited_by = invited_by
        # Все ограничения БД проверяем до SMTP: после успешного письма ссылка
        # не должна оказаться нерабочей из-за банального IntegrityError.
        await self._db.flush()
        try:
            await email_service.send_invitation(
                to=user.email,
                invitation_url=self._url(token, public_base_url),
                expires_hours=settings.INVITATION_TTL_HOURS,
            )
        except email_service.EmailNotConfiguredError as exc:
            await self._db.rollback()
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "Отправка почты не настроена. Настройте SMTP и повторите операцию.",
            ) from exc
        except email_service.EmailDeliveryError as exc:
            await self._db.rollback()
            logger.exception("Не удалось отправить приглашение | user_id=%s", user.id)
            raise HTTPException(
                status.HTTP_502_BAD_GATEWAY,
                "Письмо не отправлено. Повторите операцию позже.",
            ) from exc
        except HTTPException:
            await self._db.rollback()
            raise

        await self._db.commit()

    async def accept(self, token: str, password: str) -> tuple[User, str]:
        token_hash = self._hash_token(token.strip())
        record = await self._db.scalar(
            select(Invitation)
            .where(Invitation.token_hash == token_hash)
            .with_for_update()
        )
        if record is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Приглашение недействительно")
        if record.expires_at < self._now():
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Срок приглашения истёк. Попросите администратора отправить его повторно.",
            )

        user = await self._db.get(User, record.user_id)
        if user is None or user.status != UserStatus.invited:
            await self._db.delete(record)
            await self._db.commit()
            raise HTTPException(status.HTTP_409_CONFLICT, "Приглашение уже использовано")

        user.password_hash = self._passwords.hash_password(password)
        user.status = UserStatus.active
        await self._db.delete(record)
        await self._db.commit()
        token_value = self._tokens.create_access_token(str(user.id), user.email)
        return user, token_value

    async def status(self, token: str) -> dict:
        token_hash = self._hash_token(token.strip())
        record = await self._db.scalar(
            select(Invitation).where(Invitation.token_hash == token_hash)
        )
        if record is None:
            return {
                "status": "invalid",
                "email": None,
                "message": "Приглашение недействительно или уже использовано.",
            }

        user = await self._db.get(User, record.user_id)
        if user is None:
            return {
                "status": "invalid",
                "email": None,
                "message": "Приглашение недействительно.",
            }

        if user.status == UserStatus.active:
            return {
                "status": "accepted",
                "email": user.email,
                "message": "Аккаунт для этой почты уже создан. Войдите обычным способом.",
            }

        if user.status != UserStatus.invited:
            return {
                "status": "unavailable",
                "email": user.email,
                "message": "Аккаунт для этой почты уже не ожидает активации.",
            }

        if record.expires_at < self._now():
            return {
                "status": "expired",
                "email": user.email,
                "message": "Срок приглашения истёк. Попросите администратора отправить новое приглашение.",
            }

        return {
            "status": "pending",
            "email": user.email,
            "message": "Приглашение активно.",
        }
