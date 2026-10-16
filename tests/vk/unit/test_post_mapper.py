from datetime import datetime

from backend.db import ContentTypeEnum, PostOriginEnum
from backend.modules.vk.dto.post_mapper import VkPostMapper


def test_to_parsed_dto_normalizes_text_and_counters():
    mapper = VkPostMapper()

    dto = mapper.to_parsed_dto(
        {
            "id": 10,
            "date": 1_700_000_000,
            "text": "hello;\nworld",
            "likes": {"count": 5},
            "reposts": {"count": 2},
            "comments": {"count": 3},
            "views": {"count": 99},
        }
    )

    assert dto.id == 10
    assert isinstance(dto.date, datetime)
    assert dto.text == "hello, world"
    assert dto.likes == 5
    assert dto.reposts == 2
    assert dto.comments == 3
    assert dto.views == 99


def test_detect_content_type_by_attachments():
    mapper = VkPostMapper()

    assert mapper.detect_content_type({"attachments": []}) == ContentTypeEnum.text
    assert mapper.detect_content_type({"attachments": [{"type": "photo"}]}) == ContentTypeEnum.photo
    assert mapper.detect_content_type({"attachments": [{"type": "video"}]}) == ContentTypeEnum.video
    assert mapper.detect_content_type({"attachments": [{"type": "photo"}, {"type": "video"}]}) == ContentTypeEnum.mixed
    assert mapper.detect_content_type({"attachments": [{"type": "doc"}]}) == ContentTypeEnum.document
    assert mapper.detect_content_type({"attachments": [{"type": "poll"}]}) == ContentTypeEnum.poll
    assert mapper.detect_content_type({"attachments": [{"type": "unknown"}]}) == ContentTypeEnum.other


def test_external_ids_urls_and_tags():
    mapper = VkPostMapper()
    post = {"owner_id": -123, "id": 456, "attachments": []}

    assert mapper.external_post_id(post) == "-123_456"
    assert mapper.post_url(post) == "https://vk.com/wall-123_456"
    assert mapper.metadata_tags(post) == ["vk", PostOriginEnum.parsed.value, ContentTypeEnum.text.value]


def test_extract_media_entries_photo_video_doc():
    mapper = VkPostMapper()
    post = {
        "attachments": [
            {
                "type": "photo",
                "photo": {
                    "id": 1,
                    "sizes": [
                        {"url": "small", "width": 10},
                        {"url": "big", "width": 100},
                    ],
                },
            },
            {
                "type": "video",
                "video": {"id": 2, "owner_id": -1},
            },
            {
                "type": "doc",
                "doc": {"id": 3, "url": "https://example.com/doc.pdf"},
            },
            {
                "type": "poll",
                "poll": {"id": 4, "owner_id": -5},
            },
        ]
    }

    entries = mapper.extract_media_entries(post)

    assert [item["type"] for item in entries] == [
        ContentTypeEnum.photo,
        ContentTypeEnum.video,
        ContentTypeEnum.document,
    ]
    assert entries[0]["url"] == "big"
    assert entries[1]["url"] == "https://vk.com/video-1_2"
    assert entries[2]["url"] == "https://example.com/doc.pdf"

def test_detect_content_type_poll():
    mapper = VkPostMapper()
    post = {
        "attachments": [
            {
                "type": "poll",
                "poll": {"id": 4, "owner_id": -5},
            }
        ]
    }

    assert mapper.detect_content_type(post) == ContentTypeEnum.poll