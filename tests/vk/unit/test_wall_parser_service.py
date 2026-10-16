from pathlib import Path

import pytest

from backend.modules.vk.services.wall_parser_service import VkWallParserService
from backend.modules.vk.utils.errors import InvalidVKUrlError, VKAPIError


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append({"url": url, "params": params, "timeout": timeout})
        return FakeResponse(self.payloads.pop(0))

def test_parse_vk_community_ref_domain_and_numeric_group():
    service = VkWallParserService(session=FakeSession([]))

    assert service.parse_vk_community_ref("https://vk.com/public123") == {"owner_id": -123, "domain_label": "public123"}
    assert service.parse_vk_community_ref("my_group") == {"domain": "my_group", "domain_label": "my_group"}


@pytest.mark.parametrize("raw", [None, "", "https://vk.com/feed", "https://vk.com/id123", "https://example.com/test"])
def test_parse_vk_community_ref_invalid(raw):
    service = VkWallParserService(session=FakeSession([]))

    with pytest.raises(InvalidVKUrlError):
        service.parse_vk_community_ref(raw)  # type: ignore[arg-type]


def test_fetch_posts_paginates(monkeypatch):
    monkeypatch.setattr("backend.modules.vk.services.wall_parser_service.settings.VK_API_URL_GET", "https://api.vk.com/method/wall.get")
    monkeypatch.setattr("backend.modules.vk.services.wall_parser_service.settings.VK_API_VERSION", "5.199")
    monkeypatch.setattr("backend.modules.vk.services.wall_parser_service.settings.ACCESS_TOKEN", "token")
    monkeypatch.setattr("backend.modules.vk.services.wall_parser_service.settings.VK_PARSER_COUNT_PER_REQUEST", 2)
    monkeypatch.setattr("backend.modules.vk.services.wall_parser_service.time.sleep", lambda _: None)
    session = FakeSession([
        {"response": {"items": [{"id": 1}, {"id": 2}], "count": 3}},
        {"response": {"items": [{"id": 3}], "count": 3}},
    ])
    service = VkWallParserService(session=session)

    result = service.fetch_posts("public123", max_posts=3)

    assert [post["id"] for post in result.posts] == [1, 2, 3]
    assert result.domain_label == "public123"
    assert len(session.calls) == 2


def test_fetch_posts_invalid_target_error(monkeypatch):
    monkeypatch.setattr("backend.modules.vk.services.wall_parser_service.settings.VK_API_URL_GET", "url")
    session = FakeSession([{"error": {"error_code": 125, "error_msg": "not found"}}])
    service = VkWallParserService(session=session)

    with pytest.raises(InvalidVKUrlError):
        service.fetch_posts("public123", max_posts=1)


def test_fetch_posts_regular_vk_error(monkeypatch):
    monkeypatch.setattr("backend.modules.vk.services.wall_parser_service.settings.VK_API_URL_GET", "url")
    session = FakeSession([{"error": {"error_code": 1, "error_msg": "failed"}}])
    service = VkWallParserService(session=session)

    with pytest.raises(VKAPIError, match="failed"):
        service.fetch_posts("public123", max_posts=1)


def test_save_posts_to_csv(tmp_path: Path):
    service = VkWallParserService(session=FakeSession([]))
    path = tmp_path / "vk.csv"

    result = service.save_posts_to_csv([{"id": 1, "date": 0, "text": "hello", "likes": {}, "reposts": {}, "comments": {}, "views": {}}], path)

    assert result == path
    assert path.exists()
    assert "hello" in path.read_text(encoding="utf-8")
