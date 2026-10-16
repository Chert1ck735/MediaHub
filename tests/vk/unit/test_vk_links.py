import pytest

from backend.modules.vk.dto.dto import VkLinkType
from backend.modules.vk.links.links import parse_vk_link
from backend.modules.vk.utils.errors import InvalidVkLinkError


@pytest.mark.parametrize(
    ("raw", "expected_type", "owner_id", "post_id", "canonical"),
    [
        ("https://vk.com/wall-123_456", VkLinkType.POST, -123, 456, "https://vk.com/wall-123_456"),
        ("vk.com/club123", VkLinkType.COMMUNITY, -123, None, "https://vk.com/club123"),
        ("public777", VkLinkType.COMMUNITY, -777, None, "https://vk.com/public777"),
        ("id42", VkLinkType.PROFILE, 42, None, "https://vk.com/id42"),
        ("my_screen.name", VkLinkType.COMMUNITY, None, None, "https://vk.com/my_screen.name"),
        ("https://vk.com/some?w=wall-10_20", VkLinkType.POST, -10, 20, "https://vk.com/wall-10_20"),
    ],
)
def test_parse_vk_link_supported_formats(raw, expected_type, owner_id, post_id, canonical):
    ref = parse_vk_link(raw)

    assert ref.type == expected_type
    assert ref.owner_id == owner_id
    assert ref.post_id == post_id
    assert ref.canonical_url == canonical


@pytest.mark.parametrize(
    "raw",
    [
        None,
        "",
        "   ",
        "https://vk.com/feed",
        "https://vk.com/settings",
        "https://vk.com/im",
        "https://vk.com/кириллица",
        "https://not-vk.com/group",
        "https://vk.com/name-with-dash",
        "https://vk.com/" + "a" * 65,
    ],
)
def test_parse_vk_link_invalid_values(raw):
    with pytest.raises(InvalidVkLinkError):
        parse_vk_link(raw)

@pytest.mark.parametrize(
    "raw,expected_type,owner_id,post_id",
    [
        ("https://vk.com/wall-123_456", VkLinkType.POST, -123, 456),
        ("vk.com/wall123_456", VkLinkType.POST, 123, 456),
        ("https://vk.com/public123", VkLinkType.COMMUNITY, -123, None),
        ("https://vk.com/club123", VkLinkType.COMMUNITY, -123, None),
        ("https://vk.com/event123", VkLinkType.COMMUNITY, -123, None),
        ("https://vk.com/id123", VkLinkType.PROFILE, 123, None),
        ("some_group", VkLinkType.COMMUNITY, None, None),
        ("https://vk.com/some_group", VkLinkType.COMMUNITY, None, None),
        ("https://m.vk.com/some_group", VkLinkType.COMMUNITY, None, None),
        ("https://www.vk.com/some_group", VkLinkType.COMMUNITY, None, None),
        ("https://vk.com/some_group?w=wall-123_456", VkLinkType.POST, -123, 456),
    ],
)
def test_parse_vk_link_valid_values(raw, expected_type, owner_id, post_id):
    result = parse_vk_link(raw)

    assert result.type == expected_type
    assert result.owner_id == owner_id
    assert result.post_id == post_id