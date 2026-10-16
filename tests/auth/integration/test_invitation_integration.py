"""Интеграционные проверки полного жизненного цикла приглашения."""
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from backend.db import Invitation, Organization, OrgType, User, UserRole, UserStatus
from backend.modules.auth.services import email_service
from backend.modules.auth.services.auth_service import AuthService
from backend.modules.auth.services.invitation_service import InvitationService
from backend.modules.auth.services.password_service import PasswordService


@pytest.fixture
def sent_invitations(monkeypatch):
    sent: list[tuple[str, str]] = []

    async def fake_send(*, to: str, invitation_url: str, expires_hours: int) -> None:
        del expires_hours
        sent.append((to, invitation_url))

    monkeypatch.setattr(email_service, "send_invitation", fake_send)
    return sent


async def _invited_user(db_session) -> User:
    org = Organization(name="Тест приглашений", type=OrgType.other)
    db_session.add(org)
    await db_session.flush()
    user = User(
        email="invite@example.ru",
        first_name="Иван",
        last_name="Приглашённый",
        role=UserRole.minion,
        status=UserStatus.invited,
        organization_id=org.id,
        password_hash=PasswordService().hash_password("unavailable-random-password"),
    )
    db_session.add(user)
    await db_session.commit()
    return user


@pytest.mark.asyncio
async def test_invitation_activates_user_and_is_one_time(db_session, sent_invitations):
    user = await _invited_user(db_session)
    service = InvitationService(db_session)

    await service.issue(user)
    assert len(sent_invitations) == 1
    token = parse_qs(urlparse(sent_invitations[0][1]).query)["invite"][0]

    # До принятия приглашения вход закрыт независимо от случайного пароля.
    assert await AuthService(db_session).authenticate(user.email, "unavailable-random-password") is None

    accepted, jwt = await service.accept(token, "New-password-123!")
    assert accepted.status == UserStatus.active
    assert jwt
    assert PasswordService().verify_password("New-password-123!", accepted.password_hash)
    assert await db_session.scalar(select(Invitation.id)) is None

    with pytest.raises(HTTPException) as exc:
        await service.accept(token, "Another-password-123!")
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_expired_invitation_is_rejected(db_session, sent_invitations):
    user = await _invited_user(db_session)
    service = InvitationService(db_session)
    await service.issue(user)
    token = parse_qs(urlparse(sent_invitations[0][1]).query)["invite"][0]

    record = await db_session.scalar(select(Invitation))
    assert record is not None
    record.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    await db_session.commit()

    with pytest.raises(HTTPException) as exc:
        await service.accept(token, "New-password-123!")
    assert exc.value.status_code == 400
    assert "истёк" in exc.value.detail


def test_invitation_url_uses_current_site_origin(monkeypatch):
    monkeypatch.setattr("backend.modules.auth.services.invitation_service.settings.APP_PUBLIC_URL", "")
    monkeypatch.setattr("backend.modules.auth.services.invitation_service.settings.APP_ENV", "dev")

    url = InvitationService._url("secret-token", "https://actual.media.example.ru")

    assert url == "https://actual.media.example.ru/?invite=secret-token"
    assert "localhost" not in url
