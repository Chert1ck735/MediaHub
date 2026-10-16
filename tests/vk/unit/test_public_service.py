from types import SimpleNamespace

import pytest

from backend.modules.vk.services.public_service import VkPublicService


class FakeRepository:
    def __init__(self, *, network=True, by_group=None, fallback=None):
        self.network = SimpleNamespace(id=1) if network else None
        self.by_group = by_group
        self.fallback = fallback or []
        self.created = False

    async def get_vk_network(self):
        return self.network

    async def find_by_group_id(self, user, group_id):
        return self.by_group

    async def get_fallback_links(self, user):
        return self.fallback

    async def create_missing_default_vk_public(self, *, user, network):
        self.created = True
        return SimpleNamespace(id="created")

@pytest.mark.asyncio
async def test_get_default_public_returns_none_without_vk_network():
    service = VkPublicService(FakeRepository(network=False))

    assert await service.get_default_public(SimpleNamespace()) is None


@pytest.mark.asyncio
async def test_get_default_public_prefers_group_id_link(monkeypatch):
    monkeypatch.setattr("backend.modules.vk.services.public_service.settings.GROUP_ID", 123)
    expected = SimpleNamespace(id="existing")
    service = VkPublicService(FakeRepository(by_group=expected))

    assert await service.get_default_public(SimpleNamespace()) is expected


@pytest.mark.asyncio
async def test_get_default_public_creates_missing_group_link(monkeypatch):
    monkeypatch.setattr("backend.modules.vk.services.public_service.settings.GROUP_ID", 123)
    repo = FakeRepository(by_group=None, fallback=[])
    service = VkPublicService(repo)

    link = await service.get_default_public(SimpleNamespace())

    assert link.id == "created"
    assert repo.created is True


@pytest.mark.asyncio
async def test_get_default_public_returns_single_fallback_without_group_id(monkeypatch):
    monkeypatch.setattr("backend.modules.vk.services.public_service.settings.GROUP_ID", 0)
    expected = SimpleNamespace(id="fallback")
    service = VkPublicService(FakeRepository(fallback=[expected]))

    assert await service.get_default_public(SimpleNamespace()) is expected


@pytest.mark.asyncio
async def test_get_default_public_returns_none_when_multiple_fallbacks(monkeypatch):
    monkeypatch.setattr("backend.modules.vk.services.public_service.settings.GROUP_ID", 0)
    service = VkPublicService(FakeRepository(fallback=[SimpleNamespace(), SimpleNamespace()]))

    assert await service.get_default_public(SimpleNamespace()) is None

