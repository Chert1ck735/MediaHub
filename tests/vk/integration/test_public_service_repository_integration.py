import uuid

import pytest

from backend.db import PublicSocialLink, SocialNetwork, Public, User, Organization
from backend.db.enums import OrgType, UserRole
from backend.modules.vk.repositories.public_repository import VkPublicRepository
from backend.modules.vk.services.public_service import VkPublicService


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_get_default_public_returns_single_active_vk_link(db_session, monkeypatch):
    monkeypatch.setattr("backend.modules.vk.services.public_service.settings.GROUP_ID", 0)

    org = Organization(name="Test org", type=OrgType.government)
    db_session.add(org)
    await db_session.flush()

    user = User(
        email=f"vk-{uuid.uuid4()}@example.com",
        first_name="VK",
        last_name="Тестов",
        password_hash="x",
        role=UserRole.minion,
        organization_id=org.id,
    )
    network = SocialNetwork(code="vk", name="VK", description="ВКонтакте")
    public = Public(organization_id=org.id, name="VK Public", description="Test", is_active=True)
    db_session.add_all([user, network, public])
    await db_session.flush()

    link = PublicSocialLink(
        public_id=public.id,
        social_network_id=network.id,
        title="VK Public",
        url="https://vk.com/test_public",
        external_public_id="123",
        is_primary=True,
        is_active=True,
    )
    db_session.add(link)
    await db_session.commit()

    service = VkPublicService(VkPublicRepository(db_session))

    result = await service.get_default_public(user)

    assert result is not None
    assert result.id == link.id
