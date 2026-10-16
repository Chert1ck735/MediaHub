import pytest

from backend.modules.vk.dto.dto import VkLinkRef, VkLinkType
from backend.modules.vk.services.owner_resolver_service import VkOwnerResolverService
from backend.modules.vk.utils.errors import IngestionError, VkApiError


class FakeApiClient:
    def __init__(self):
        self.group = {"id": 123, "screen_name": "club123", "name": "Test Group", "description": "Desc", "members_count": 50}
        self.user = {"id": 42, "screen_name": "id42", "first_name": "Ivan", "last_name": "Petrov", "about": "About"}
        self.user_followers_count = 77
        self.screen = {"type": "group", "object_id": 123}

    def resolve_screen_name(self, screen_name):
        return self.screen

    def get_group(self, group_ref):
        return self.group

    def get_user(self, user_ref):
        return self.user

    def get_user_followers_count(self, user_ref):
        return self.user_followers_count


def test_resolve_screen_name_group():
    service = VkOwnerResolverService(FakeApiClient())
    ref = VkLinkRef(type=VkLinkType.COMMUNITY, raw_url="vk.com/test", canonical_url="https://vk.com/test", domain="test")

    resolved = service.resolve_screen_name(ref)

    assert resolved.type == VkLinkType.COMMUNITY
    assert resolved.owner_id == -123


def test_resolve_screen_name_user():
    api = FakeApiClient()
    api.screen = {"type": "user", "object_id": 42}
    service = VkOwnerResolverService(api)
    ref = VkLinkRef(type=VkLinkType.COMMUNITY, raw_url="vk.com/test", canonical_url="https://vk.com/test", domain="test")

    resolved = service.resolve_screen_name(ref)

    assert resolved.type == VkLinkType.PROFILE
    assert resolved.owner_id == 42


def test_resolve_community_owner():
    service = VkOwnerResolverService(FakeApiClient())
    ref = VkLinkRef(type=VkLinkType.COMMUNITY, raw_url="vk.com/club123", canonical_url="https://vk.com/club123", owner_id=-123)

    owner = service.resolve_community_owner(ref)

    assert owner.name == "Test Group"
    assert owner.owner_id == -123
    assert owner.external_public_id == "123"
    assert owner.members_count == 50


def test_resolve_profile_owner_uses_users_get_followers_count():
    api = FakeApiClient()
    api.user = {"id": 42, "screen_name": "id42", "first_name": "Ivan", "last_name": "Petrov", "followers_count": 5}
    api.user_followers_count = 77
    service = VkOwnerResolverService(api)
    ref = VkLinkRef(type=VkLinkType.PROFILE, raw_url="vk.com/id42", canonical_url="https://vk.com/id42", owner_id=42)

    owner = service.resolve_profile_owner(ref)

    assert owner.members_count == 77


def test_resolve_profile_owner_falls_back_to_users_get_fields_on_followers_error():
    class FollowersDeniedApi(FakeApiClient):
        def get_user_followers_count(self, user_ref):
            raise VkApiError("private", code=30)

    api = FollowersDeniedApi()
    api.user = {"id": 42, "screen_name": "id42", "first_name": "Ivan", "last_name": "Petrov", "counters": {"followers": 12}}
    service = VkOwnerResolverService(api)
    ref = VkLinkRef(type=VkLinkType.PROFILE, raw_url="vk.com/id42", canonical_url="https://vk.com/id42", owner_id=42)

    owner = service.resolve_profile_owner(ref)

    assert owner.members_count == 12


def test_resolve_profile_owner_deactivated_raises():
    api = FakeApiClient()
    api.user = {"id": 42, "deactivated": "deleted"}
    service = VkOwnerResolverService(api)
    ref = VkLinkRef(type=VkLinkType.PROFILE, raw_url="vk.com/id42", canonical_url="https://vk.com/id42", owner_id=42)

    with pytest.raises(IngestionError):
        service.resolve_profile_owner(ref)


def test_vk_api_error_is_wrapped_to_ingestion_error():
    class BrokenApi(FakeApiClient):
        def get_group(self, group_ref):
            raise VkApiError("broken", code=125)

    service = VkOwnerResolverService(BrokenApi())
    ref = VkLinkRef(type=VkLinkType.COMMUNITY, raw_url="vk.com/club123", canonical_url="https://vk.com/club123", owner_id=-123)

    with pytest.raises(IngestionError, match="groups.getById"):
        service.resolve_community_owner(ref)
