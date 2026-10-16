"""Коды подтверждения почты: выдача, проверка, срок жизни.

Вся логика на сервере. Клиент не видит код, не хранит его и не решает, что
почта подтверждена — он только сообщает, что ввёл пользователь.

Защита, без которой шестизначный код бесполезен:
* ``EMAIL_CODE_MAX_ATTEMPTS`` — иначе 10^6 вариантов перебираются скриптом за
  минуты;
* cooldown между отправками — иначе форма становится бесплатным спам-шлюзом по
  чужим адресам;
* TTL — код не живёт вечно;
* хранится хеш кода, а не код: дамп БД не должен давать возможность
  подтвердить чужую почту.
"""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.config import settings
from backend.db.email_verifications import EmailVerification
from backend.db.users import User
from backend.modules.auth.services import email_service
from backend.modules.auth.services.password_service import PasswordService

# Сколько времени подтверждение остаётся действительным ПОСЛЕ ввода кода —
# столько у пользователя есть на то, чтобы дозаполнить форму регистрации.
VERIFIED_WINDOW = timedelta(minutes=30)


class VerificationService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._passwords = PasswordService()

    @staticmethod
    def _now() -> datetime:
        # timezone-aware: колонки timestamptz, наивный datetime записал бы
        # неверный момент.
        return datetime.now(timezone.utc)

    @staticmethod
    def _generate_code() -> str:
        """Шестизначный код. secrets, а не random: random предсказуем."""
        return f"{secrets.randbelow(1_000_000):06d}"

    async def _get(self, email: str) -> EmailVerification | None:
        return (
            await self._db.execute(
                select(EmailVerification).where(EmailVerification.email == email)
            )
        ).scalar_one_or_none()

    async def send_code(self, email: str) -> None:
        """Выдаёт новый код и отправляет письмо.

        Повторная отправка перезаписывает прежний код: старый сразу
        недействителен, иначе на один адрес копилось бы несколько живых кодов.
        """
        email = email.strip().lower()

        # Регистрироваться на занятую почту нельзя — говорим об этом сразу, а не
        # после ввода кода. Перечисление адресов тут ничего не добавляет: тот же
        # ответ даёт и сама регистрация.
        existing_user = await self._db.scalar(select(User.id).where(User.email == email))
        if existing_user is not None:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Эта почта уже зарегистрирована",
            )

        now = self._now()
        record = await self._get(email)

        if record is not None:
            elapsed = (now - record.last_sent_at).total_seconds()
            cooldown = settings.EMAIL_CODE_RESEND_COOLDOWN_SECONDS
            if elapsed < cooldown:
                raise HTTPException(
                    status.HTTP_429_TOO_MANY_REQUESTS,
                    f"Новый код можно запросить через {int(cooldown - elapsed)} с",
                )

        code = self._generate_code()
        code_hash = self._passwords.hash_password(code)
        expires_at = now + timedelta(minutes=settings.EMAIL_CODE_TTL_MINUTES)

        if record is None:
            record = EmailVerification(email=email)
            self._db.add(record)

        record.code_hash = code_hash
        record.expires_at = expires_at
        record.attempts = 0
        record.last_sent_at = now
        record.verified_at = None

        # Коммитим ДО отправки: письмо уходит секунды, и держать транзакцию
        # открытой на время сетевого вызова нельзя.
        await self._db.commit()

        try:
            await email_service.send_verification_code(to=email, code=code)
        except email_service.EmailNotConfiguredError as exc:
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "Отправка почты не настроена. Обратитесь к администратору.",
            ) from exc
        except email_service.EmailDeliveryError as exc:
            raise HTTPException(
                status.HTTP_502_BAD_GATEWAY,
                "Не удалось отправить письмо. Попробуйте позже.",
            ) from exc

    async def send_reset_code(self, email: str) -> None:
        """Код для восстановления забытого пароля.

        Незнакомый адрес не отличим от знакомого: выходим молча и без cooldown,
        иначе форма становится проверкой «кто здесь зарегистрирован».
        """
        email = email.strip().lower()

        user = await self._db.scalar(select(User.id).where(User.email == email))
        if user is None:
            return

        now = self._now()
        record = await self._get(email)

        if record is not None:
            elapsed = (now - record.last_sent_at).total_seconds()
            cooldown = settings.EMAIL_CODE_RESEND_COOLDOWN_SECONDS
            if elapsed < cooldown:
                raise HTTPException(
                    status.HTTP_429_TOO_MANY_REQUESTS,
                    f"Новый код можно запросить через {int(cooldown - elapsed)} с",
                )

        code = self._generate_code()

        if record is None:
            record = EmailVerification(email=email)
            self._db.add(record)

        record.code_hash = self._passwords.hash_password(code)
        record.expires_at = now + timedelta(minutes=settings.EMAIL_CODE_TTL_MINUTES)
        record.attempts = 0
        record.last_sent_at = now
        record.verified_at = None

        await self._db.commit()

        try:
            await email_service.send_password_reset_code(to=email, code=code)
        except email_service.EmailNotConfiguredError as exc:
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "Отправка почты не настроена. Обратитесь к администратору.",
            ) from exc
        except email_service.EmailDeliveryError as exc:
            raise HTTPException(
                status.HTTP_502_BAD_GATEWAY,
                "Не удалось отправить письмо. Попробуйте позже.",
            ) from exc

    async def consume_code(self, email: str, code: str) -> None:
        """Сверяет код и удаляет запись: иначе тем же кодом пароль сменят повторно."""
        await self.verify_code(email, code)

        record = await self._get(email.strip().lower())
        if record is not None:
            await self._db.delete(record)
            await self._db.flush()

    async def verify_code(self, email: str, code: str) -> None:
        """Сверяет код. Бросает 400, если не сошлось."""
        email = email.strip().lower()
        code = code.strip()

        record = await self._get(email)
        if record is None:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "Сначала запросите код подтверждения"
            )

        now = self._now()
        if record.expires_at < now:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "Код истёк. Запросите новый."
            )

        if record.attempts >= settings.EMAIL_CODE_MAX_ATTEMPTS:
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                "Слишком много попыток. Запросите новый код.",
            )

        if not self._passwords.verify_password(code, record.code_hash):
            # Счётчик увеличиваем ДО ответа и коммитим: иначе перебор
            # обходится тем, что клиент просто не ждёт ответа.
            record.attempts += 1
            await self._db.commit()
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Неверный код")

        record.verified_at = now
        await self._db.commit()

    async def consume_verified(self, email: str) -> None:
        """Проверяет, что почта подтверждена, и гасит подтверждение.

        Вызывается регистрацией. Одноразовость важна: без неё одно
        подтверждение позволяло бы регистрировать аккаунт повторно.
        """
        email = email.strip().lower()
        record = await self._get(email)

        if record is None or record.verified_at is None:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "Почта не подтверждена. Запросите код и введите его.",
            )

        if self._now() - record.verified_at > VERIFIED_WINDOW:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "Подтверждение устарело. Запросите код заново.",
            )

        await self._db.delete(record)
        await self._db.flush()
