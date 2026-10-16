"""HTTP-уровень: прямой запрос в обход UI обязан получить 403.

Сервисные тесты проверяют логику, но ТЗ требует именно поведения API. Здесь
запрос идёт через настоящее FastAPI-приложение: роутинг, зависимости,
аутентификацию и сериализацию ответа — то есть ровно тем путём, которым пойдёт
злоумышленник с curl.
"""
from __future__ import annotations

import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from backend.app.main import app
from backend.db import Organization, Public, User
from backend.db.database import get_db
from backend.db.enums import OrgType, UserRole, UserStatus
from backend.modules.auth.deps import get_current_user

pytestmark = [
    pytest.mark.integration,
    pytest.mark.asyncio(loop_scope="session"),
]


async def _seed(session, role: UserRole) -> tuple[Organization, User, Public]:
    org = Organization(name=f"Орг-{uuid.uuid4()}", type=OrgType.government)
    session.add(org)
    await session.flush()

    user = User(
        first_name="Тест",
        last_name="Юзеров",
        email=f"{uuid.uuid4()}@x.ru",
        password_hash="x",
        role=role,
        status=UserStatus.active,
        organization_id=org.id,
    )
    public = Public(organization_id=org.id, name=f"Паблик-{uuid.uuid4()}")
    session.add_all([user, public])
    await session.flush()
    await session.commit()
    return org, user, public


def _client(session, actor: User) -> AsyncClient:
    """Клиент к настоящему приложению.

    Подменяем только БД-сессию и текущего пользователя: сам роутинг, проверки
    прав и сериализация остаются боевыми — иначе тест проверял бы не то.
    """
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_current_user] = lambda: actor
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_minion_gets_403_on_organization_settings(db_session):
    """MINION лезет в настройки организации напрямую — 403, а не пустой список."""
    org, minion, _ = await _seed(db_session, UserRole.minion)
    try:
        async with _client(db_session, minion) as client:
            response = await client.get(f"/api/organizations/{org.id}/users")
        assert response.status_code == 403
    finally:
        app.dependency_overrides.clear()


async def test_admin_gets_403_on_foreign_organization(db_session):
    """ADMIN одной организации читает пользователей другой — 403."""
    _, admin_a, _ = await _seed(db_session, UserRole.admin)
    org_b, _, _ = await _seed(db_session, UserRole.admin)
    try:
        async with _client(db_session, admin_a) as client:
            response = await client.get(f"/api/organizations/{org_b.id}/users")
        assert response.status_code == 403
    finally:
        app.dependency_overrides.clear()


async def test_admin_can_list_own_organization_users(db_session):
    """Своя организация — 200 и данные на месте."""
    org, admin, _ = await _seed(db_session, UserRole.admin)
    try:
        async with _client(db_session, admin) as client:
            response = await client.get(f"/api/organizations/{org.id}/users")
        assert response.status_code == 200
        body = response.json()
        assert body["total"] >= 1
        assert any(item["email"] == admin.email for item in body["items"])
    finally:
        app.dependency_overrides.clear()


async def test_minion_gets_403_creating_grants(db_session):
    """Раздача прав самому себе напрямую через API — 403."""
    org, minion, public = await _seed(db_session, UserRole.minion)
    try:
        async with _client(db_session, minion) as client:
            response = await client.put(
                f"/api/organizations/{org.id}/grants",
                json={
                    "subject_type": "user",
                    "subject_id": str(minion.id),
                    "grants": [
                        {
                            "resource_type": "community",
                            "resource_id": str(public.id),
                            "permission": "create_post",
                        }
                    ],
                },
            )
        assert response.status_code == 403
    finally:
        app.dependency_overrides.clear()


async def test_minion_gets_403_on_user_import(db_session):
    """Импорт пользователей — только админ."""
    org, minion, _ = await _seed(db_session, UserRole.minion)
    try:
        async with _client(db_session, minion) as client:
            response = await client.post(
                f"/api/organizations/{org.id}/users/import/preview",
                files={"file": ("users.csv", b"email\nx@y.ru\n", "text/csv")},
            )
        assert response.status_code == 403
    finally:
        app.dependency_overrides.clear()
