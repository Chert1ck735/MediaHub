"""Подтверждение почты кодом — серверная проверка.

Каждый тест здесь закрывает конкретную дыру старой схемы, где код генерировался
в браузере, хранился в localStorage и показывался на экране.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from backend.app.config import settings
from backend.app.main import app
from backend.db import EmailVerification, Organization, User
from backend.db.database import get_db
from backend.db.enums import OrgType, UserRole, UserStatus
from backend.modules.auth.services import email_service
from backend.modules.auth.services.auth_service import AuthService
from backend.modules.auth.services.verification_service import VerificationService

pytestmark = [
    pytest.mark.integration,
    pytest.mark.asyncio(loop_scope="session"),
]


@pytest.fixture
def sent_codes(monkeypatch):
    """Перехватывает отправку письма и запоминает коды.

    Так тест видит код, а КЛИЕНТ — нет: в этом вся суть.
    """
    captured: list[tuple[str, str]] = []

    async def fake_send(*, to: str, code: str) -> None:
        captured.append((to, code))

    monkeypatch.setattr(email_service, "send_verification_code", fake_send)
    return captured


def _client(session) -> AsyncClient:
    app.dependency_overrides[get_db] = lambda: session
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _record(session, email: str) -> EmailVerification:
    return (
        await session.execute(
            select(EmailVerification).where(EmailVerification.email == email)
        )
    ).scalar_one()


# ── код не утекает клиенту ──────────────────────────────────────────────────

async def test_send_code_response_never_contains_the_code(db_session, sent_codes):
    """Главное свойство: код существует только в письме.

    Раньше фронт печатал его на экране («Тестовый код: 123456») — проверка
    почты не значила ничего.
    """
    email = f"{uuid.uuid4()}@example.ru"
    try:
        async with _client(db_session) as client:
            response = await client.post("/api/auth/send-code", json={"email": email})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 204
    assert response.content == b""

    # Код ушёл в письмо…
    assert len(sent_codes) == 1
    _, code = sent_codes[0]
    assert len(code) == 6 and code.isdigit()

    # …а в БД лежит только его ХЕШ, не он сам.
    record = await _record(db_session, email)
    assert code not in record.code_hash


# ── регистрация без подтверждения ───────────────────────────────────────────

async def test_register_without_verification_is_rejected(db_session):
    """Регистрация без кода — 403. Раньше проходила беспрепятственно."""
    with pytest.raises(HTTPException) as exc:
        await AuthService(db_session).register(
            email=f"{uuid.uuid4()}@example.ru",
            name="Иван",
            password="secret123",
        )
    assert exc.value.status_code == 403


async def test_register_succeeds_after_verification(db_session, sent_codes):
    email = f"{uuid.uuid4()}@example.ru"
    service = VerificationService(db_session)

    await service.send_code(email)
    _, code = sent_codes[0]
    await service.verify_code(email, code)

    user, token = await AuthService(db_session).register(
        email=email, name="Иван Тихонов", password="secret123"
    )
    assert user.email == email
    assert token

    # Подтверждение одноразовое: после регистрации записи нет.
    left = await db_session.scalar(
        select(EmailVerification.id).where(EmailVerification.email == email)
    )
    assert left is None


async def test_verification_cannot_be_reused(db_session, sent_codes):
    """Одно подтверждение — одна регистрация."""
    email = f"{uuid.uuid4()}@example.ru"
    service = VerificationService(db_session)
    await service.send_code(email)
    await service.verify_code(email, sent_codes[0][1])
    await service.consume_verified(email)

    with pytest.raises(HTTPException) as exc:
        await service.consume_verified(email)
    assert exc.value.status_code == 403


# ── захват аккаунта ─────────────────────────────────────────────────────────

async def test_register_on_existing_email_does_not_reset_password(db_session):
    """Регистрация на занятую почту НЕ перезаписывает пароль.

    Раньше register молча менял пароль существующему пользователю и выдавал
    токен — то есть «регистрация» на чужой адрес была захватом аккаунта.
    """
    org = Organization(name=f"Орг-{uuid.uuid4()}", type=OrgType.government)
    db_session.add(org)
    await db_session.flush()

    email = f"{uuid.uuid4()}@example.ru"
    victim = User(
        first_name="Жертва",
        last_name="Жертвова",
        email=email,
        password_hash="ОРИГИНАЛЬНЫЙ_ХЕШ",
        role=UserRole.admin,
        status=UserStatus.active,
        organization_id=org.id,
    )
    db_session.add(victim)
    await db_session.commit()

    with pytest.raises(HTTPException) as exc:
        await AuthService(db_session).register(
            email=email, name="Злоумышленник", password="hacked"
        )
    assert exc.value.status_code == 409

    await db_session.refresh(victim)
    assert victim.password_hash == "ОРИГИНАЛЬНЫЙ_ХЕШ"


async def test_send_code_to_registered_email_is_rejected(db_session, sent_codes):
    org = Organization(name=f"Орг-{uuid.uuid4()}", type=OrgType.government)
    db_session.add(org)
    await db_session.flush()

    email = f"{uuid.uuid4()}@example.ru"
    db_session.add(
        User(
            first_name="Уже",
            last_name="Есть",
            email=email,
            password_hash="x",
            role=UserRole.minion,
            status=UserStatus.active,
            organization_id=org.id,
        )
    )
    await db_session.commit()

    with pytest.raises(HTTPException) as exc:
        await VerificationService(db_session).send_code(email)
    assert exc.value.status_code == 409
    assert sent_codes == []  # письмо не ушло


# ── защита кода ─────────────────────────────────────────────────────────────

async def test_wrong_code_is_rejected_and_counted(db_session, sent_codes):
    email = f"{uuid.uuid4()}@example.ru"
    service = VerificationService(db_session)
    await service.send_code(email)

    with pytest.raises(HTTPException) as exc:
        await service.verify_code(email, "000000")
    assert exc.value.status_code == 400

    record = await _record(db_session, email)
    assert record.attempts == 1
    assert record.verified_at is None


async def test_bruteforce_is_stopped_after_max_attempts(db_session, sent_codes):
    """Шестизначный код без лимита попыток перебирается скриптом за минуты."""
    email = f"{uuid.uuid4()}@example.ru"
    service = VerificationService(db_session)
    await service.send_code(email)
    _, real_code = sent_codes[0]

    for _ in range(settings.EMAIL_CODE_MAX_ATTEMPTS):
        with pytest.raises(HTTPException):
            await service.verify_code(email, "000000")

    # Даже ПРАВИЛЬНЫЙ код больше не принимается — нужен новый.
    with pytest.raises(HTTPException) as exc:
        await service.verify_code(email, real_code)
    assert exc.value.status_code == 429


async def test_expired_code_is_rejected(db_session, sent_codes):
    email = f"{uuid.uuid4()}@example.ru"
    service = VerificationService(db_session)
    await service.send_code(email)
    _, code = sent_codes[0]

    record = await _record(db_session, email)
    record.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    await db_session.commit()

    with pytest.raises(HTTPException) as exc:
        await service.verify_code(email, code)
    assert exc.value.status_code == 400


async def test_resend_cooldown_blocks_spam(db_session, sent_codes):
    """Без cooldown форма — бесплатный спам-шлюз по чужим адресам."""
    email = f"{uuid.uuid4()}@example.ru"
    service = VerificationService(db_session)
    await service.send_code(email)

    with pytest.raises(HTTPException) as exc:
        await service.send_code(email)
    assert exc.value.status_code == 429
    assert len(sent_codes) == 1  # второе письмо не ушло


async def test_resend_invalidates_previous_code(db_session, sent_codes, monkeypatch):
    """Новый код отменяет старый — иначе на адрес копятся живые коды."""
    monkeypatch.setattr(settings, "EMAIL_CODE_RESEND_COOLDOWN_SECONDS", 0)

    email = f"{uuid.uuid4()}@example.ru"
    service = VerificationService(db_session)

    await service.send_code(email)
    first_code = sent_codes[0][1]
    await service.send_code(email)
    second_code = sent_codes[1][1]

    if first_code != second_code:  # мизерный шанс совпадения 1/10^6
        with pytest.raises(HTTPException):
            await service.verify_code(email, first_code)

    await service.verify_code(email, second_code)
    record = await _record(db_session, email)
    assert record.verified_at is not None
