import pytest

from backend.modules.ok.dto.dto import OkLinkType
from backend.modules.ok.links.links import parse_ok_link
from backend.modules.ok.utils.errors import InvalidOkLinkError


@pytest.mark.parametrize(
    ("raw", "expected_type", "group_ref", "topic_id", "canonical"),
    [
        (
            "https://ok.ru/group/70000001234567",
            OkLinkType.GROUP,
            "70000001234567",
            None,
            "https://ok.ru/group/70000001234567",
        ),
        ("https://ok.ru/group/mygroup", OkLinkType.GROUP, "mygroup", None, "https://ok.ru/group/mygroup"),
        ("http://m.ok.ru/group/mygroup", OkLinkType.GROUP, "mygroup", None, "https://ok.ru/group/mygroup"),
        ("https://www.ok.ru/group/mygroup/", OkLinkType.GROUP, "mygroup", None, "https://ok.ru/group/mygroup"),
        ("https://odnoklassniki.ru/group/mygroup", OkLinkType.GROUP, "mygroup", None, "https://ok.ru/group/mygroup"),
        ("ok.ru/group/mygroup", OkLinkType.GROUP, "mygroup", None, "https://ok.ru/group/mygroup"),
        ("mygroup", OkLinkType.GROUP, "mygroup", None, "https://ok.ru/group/mygroup"),
        ("https://ok.ru/mygroup", OkLinkType.GROUP, "mygroup", None, "https://ok.ru/group/mygroup"),
        (
            "https://ok.ru/group/70000001234567/topic/155555555",
            OkLinkType.TOPIC,
            "70000001234567",
            "155555555",
            "https://ok.ru/group/70000001234567/topic/155555555",
        ),
        (
            "https://ok.ru/group/mygroup/topic/155555555?st._aid=FeedTopic",
            OkLinkType.TOPIC,
            "mygroup",
            "155555555",
            "https://ok.ru/group/mygroup/topic/155555555",
        ),
        ("https://m.ok.ru/topic/155555555", OkLinkType.TOPIC, None, "155555555", "https://ok.ru/topic/155555555"),
    ],
)
def test_parse_ok_link_supported_formats(raw, expected_type, group_ref, topic_id, canonical):
    ref = parse_ok_link(raw)

    assert ref.type == expected_type
    assert ref.group_ref == group_ref
    assert ref.topic_id == topic_id
    assert ref.canonical_url == canonical


@pytest.mark.parametrize(
    ("raw", "profile_ref"),
    [
        ("https://ok.ru/profile/123456789012", "123456789012"),
        ("https://ok.ru/profile/somenick", "somenick"),
    ],
)
def test_parse_ok_link_profile(raw, profile_ref):
    ref = parse_ok_link(raw)

    assert ref.type == OkLinkType.PROFILE
    assert ref.profile_ref == profile_ref


def test_numeric_group_link_exposes_group_id():
    """Числовой uid можно использовать без обращения к group.getInfo."""
    assert parse_ok_link("https://ok.ru/group/70000001234567").group_id == "70000001234567"


def test_shortname_group_link_has_no_group_id():
    """Короткое имя — не идентификатор: id появится только после group.getInfo."""
    assert parse_ok_link("https://ok.ru/group/mygroup").group_id is None


@pytest.mark.parametrize(
    "raw",
    [
        None,
        "",
        "   ",
        "https://ok.ru/",
        "https://ok.ru/feed",
        "https://ok.ru/video",
        "https://ok.ru/messages",
        "https://ok.ru/group",
        "https://ok.ru/profile",
        "https://ok.ru/12345",  # числовой id без раздела неоднозначен
        "https://ok.ru/group/mygroup/topic/abc",  # нечисловая тема
        "https://ok.ru/группа",
        "https://not-ok.com/group/x",
        "https://ok.ru/" + "a" * 65,
    ],
)
def test_parse_ok_link_invalid_values(raw):
    with pytest.raises(InvalidOkLinkError):
        parse_ok_link(raw)
