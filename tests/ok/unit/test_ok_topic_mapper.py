from datetime import timezone

from backend.db import ContentTypeEnum
from backend.modules.ok.dto.topic_mapper import OkTopicMapper


def _topic(**overrides):
    topic = {"id": "111", "created_ms": 1_700_000_000_000, "media": []}
    topic.update(overrides)
    return topic


def test_extract_text_from_plain_text_block():
    mapper = OkTopicMapper()
    topic = _topic(media=[{"type": "text", "text": "Первая строка"}])

    assert mapper.extract_text(topic) == "Первая строка"


def test_extract_text_falls_back_to_text_tokens():
    """OK отдаёт текст либо строкой, либо набором токенов."""
    mapper = OkTopicMapper()
    topic = _topic(media=[{"type": "text", "text_tokens": [{"text": "Соб"}, {"text": "ранный"}]}])

    assert mapper.extract_text(topic) == "Собранный"


def test_extract_text_falls_back_to_title():
    mapper = OkTopicMapper()

    assert mapper.extract_text(_topic(title="Заголовок")) == "Заголовок"


def test_extract_text_joins_multiple_text_blocks():
    mapper = OkTopicMapper()
    topic = _topic(media=[{"type": "text", "text": "Раз"}, {"type": "text", "text": "Два"}])

    assert mapper.extract_text(topic) == "Раз\nДва"


def test_detect_content_type_ignores_text_blocks():
    mapper = OkTopicMapper()
    topic = _topic(media=[{"type": "text", "text": "x"}, {"type": "photo", "list": []}])

    assert mapper.detect_content_type(topic) == ContentTypeEnum.photo


def test_detect_content_type_mixed():
    mapper = OkTopicMapper()
    topic = _topic(media=[{"type": "photo", "list": []}, {"type": "video", "url": "u"}])

    assert mapper.detect_content_type(topic) == ContentTypeEnum.mixed


def test_detect_content_type_text_only():
    mapper = OkTopicMapper()

    assert mapper.detect_content_type(_topic(media=[{"type": "text", "text": "x"}])) == ContentTypeEnum.text


def test_external_post_id_and_url():
    mapper = OkTopicMapper()
    topic = _topic()

    assert mapper.external_post_id("70000", topic) == "70000_111"
    assert mapper.post_url("70000", topic) == "https://ok.ru/group/70000/topic/111"


def test_published_at_converts_milliseconds_to_utc():
    mapper = OkTopicMapper()

    published = mapper.published_at(_topic(created_ms=1_700_000_000_000))

    assert published.tzinfo == timezone.utc
    assert int(published.timestamp() * 1000) == 1_700_000_000_000


def test_extract_media_entries_picks_largest_photo():
    mapper = OkTopicMapper()
    topic = _topic(
        media=[{"type": "photo", "list": [{"id": "p1", "pic320min": "small", "pic1024x768": "big"}]}]
    )

    entries = mapper.extract_media_entries(topic)

    assert entries == [
        {"url": "big", "type": ContentTypeEnum.photo, "external_id": "p1", "sort_order": 0}
    ]


def test_stats_uses_reach_when_views_missing():
    mapper = OkTopicMapper()

    stats = mapper.stats({"id": "111", "likes": 3, "comments": 2, "reshares": 1, "reach": 42})

    assert (stats.views, stats.likes, stats.comments, stats.reshares) == (42, 3, 2, 1)


def test_comment_author_id_from_author_ref():
    mapper = OkTopicMapper()

    assert mapper.comment_author_id({"author_ref": "user:555"}) == "555"
    assert mapper.comment_author_id({"author_id": "777"}) == "777"
    assert mapper.comment_author_id({}) is None


def test_comment_text_from_tokens():
    mapper = OkTopicMapper()

    assert mapper.comment_text({"text_tokens": [{"text": "Из "}, {"text": "токенов"}]}) == "Из токенов"


def test_comment_parent_id_supports_both_keys():
    mapper = OkTopicMapper()

    assert mapper.comment_parent_id({"reply_to_comment_id": "c1"}) == "c1"
    assert mapper.comment_parent_id({"reply_to_id": "c2"}) == "c2"
    assert mapper.comment_parent_id({}) is None
