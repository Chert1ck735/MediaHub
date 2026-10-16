import pytest
import requests

from backend.modules.vk.utils.api_client import VkApiClient
from backend.modules.vk.utils.errors import VkApiError


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def json(self):
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload

class FakeSession:
    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append({"url": url, "params": params, "timeout": timeout})
        payload = self.payloads.pop(0)
        if isinstance(payload, requests.exceptions.RequestException):
            raise payload
        return FakeResponse(payload)

def test_call_adds_token_version_and_returns_response(monkeypatch):
    monkeypatch.setattr("backend.modules.vk.utils.api_client.settings.ACCESS_TOKEN", "token")
    monkeypatch.setattr("backend.modules.vk.utils.api_client.settings.VK_API_VERSION", "5.199")
    monkeypatch.setattr("backend.modules.vk.utils.api_client.time.sleep", lambda _: None)
    session = FakeSession([{"response": {"ok": True}}])
    client = VkApiClient(session=session)

    response = client.call("test.method", {"x": 1})

    assert response == {"ok": True}
    assert session.calls[0]["params"]["access_token"] == "token"
    assert session.calls[0]["params"]["v"] == "5.199"
    assert session.calls[0]["params"]["x"] == 1

def test_call_retries_rate_limit(monkeypatch):
    monkeypatch.setattr("backend.modules.vk.utils.api_client.settings.ACCESS_TOKEN", "token")
    monkeypatch.setattr("backend.modules.vk.utils.api_client.time.sleep", lambda _: None)
    session = FakeSession([
        {"error": {"error_code": 6, "error_msg": "Too many requests"}},
        {"response": {"ok": True}},
    ])
    client = VkApiClient(session=session)

    assert client.call("test.method", {}) == {"ok": True}
    assert len(session.calls) == 2

def test_call_raises_vk_api_error(monkeypatch):
    monkeypatch.setattr("backend.modules.vk.utils.api_client.settings.ACCESS_TOKEN", "token")
    monkeypatch.setattr("backend.modules.vk.utils.api_client.time.sleep", lambda _: None)
    session = FakeSession([{"error": {"error_code": 125, "error_msg": "not found"}}])
    client = VkApiClient(session=session)

    with pytest.raises(VkApiError) as exc:
        client.call("groups.getById", {})

    assert exc.value.code == 125

def test_fetch_all_wall_paginates(monkeypatch):
    monkeypatch.setattr("backend.modules.vk.utils.api_client.settings.ACCESS_TOKEN", "token")
    monkeypatch.setattr("backend.modules.vk.utils.api_client.time.sleep", lambda _: None)
    client = VkApiClient(session=FakeSession([]))
    pages = [
        {"items": [{"id": 1}, {"id": 2}], "count": 3},
        {"items": [{"id": 3}], "count": 3},
    ]
    client.wall_get = lambda **kwargs: pages.pop(0)  # type: ignore[method-assign]

    assert client.fetch_all_wall(owner_id=-1, max_posts=3) == [{"id": 1}, {"id": 2}, {"id": 3}]


def test_get_user_followers_count_uses_users_get_followers(monkeypatch):
    monkeypatch.setattr("backend.modules.vk.utils.api_client.settings.ACCESS_TOKEN", "token")
    monkeypatch.setattr("backend.modules.vk.utils.api_client.time.sleep", lambda _: None)
    session = FakeSession([{"response": {"count": 321, "items": []}}])
    client = VkApiClient(session=session)

    assert client.get_user_followers_count(42) == 321
    assert session.calls[0]["url"].endswith("/users.getFollowers")
    assert session.calls[0]["params"]["user_id"] == 42
    assert session.calls[0]["params"]["count"] == 0


def test_fetch_all_comments_deduplicates_thread_items(monkeypatch):
    monkeypatch.setattr("backend.modules.vk.utils.api_client.settings.ACCESS_TOKEN", "token")
    monkeypatch.setattr("backend.modules.vk.utils.api_client.time.sleep", lambda _: None)
    client = VkApiClient(session=FakeSession([]))
    client.wall_get_comments = lambda **kwargs: {  # type: ignore[method-assign]
        "count": 2,
        "items": [
            {"id": 10, "text": "same", "thread": {"items": [{"id": 10, "text": "same"}]}},
            {"id": 11, "text": "other"},
        ],
    }

    comments = client.fetch_all_comments(owner_id=-1, post_id=1, max_comments=10)

    assert comments == [
        {"id": 10, "text": "same", "thread": {"items": [{"id": 10, "text": "same"}]}},
        {"id": 11, "text": "other"},
    ]
