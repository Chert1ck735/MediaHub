"""Характеристик-тесты: comment_examples (URL, дедуп и лимиты примеров)."""
from __future__ import annotations

import uuid

from backend.db.enums import SentimentEnum
from backend.modules.analytics.utils.comment_examples import (
    append_comment_example_to_list,
    coerce_comment_examples,
    comment_example_from_string,
    legacy_comment_examples,
    vk_comment_url,
)


def test_vk_comment_url_branches():
    assert vk_comment_url("https://vk.com/wall-1_2", "5") == "https://vk.com/wall-1_2?reply=5"
    assert vk_comment_url(None, "5") is None
    assert vk_comment_url("https://vk.com/wall-1_2", None) == "https://vk.com/wall-1_2"
    # уже есть ?reply= — не дублируем
    assert vk_comment_url("https://vk.com/wall-1_2?reply=9", "5") == "https://vk.com/wall-1_2?reply=9"


def test_comment_example_from_string():
    ex = comment_example_from_string("текст комментария", "complaint")
    assert ex["text"] == "текст комментария"
    assert ex["message_type"] == "complaint"
    assert ex["url"] is None
    assert ex["sentiment"] is None


def test_coerce_comment_examples_dedups_and_filters():
    raw = [
        {"text": "привет", "url": "u1"},
        {"text": "привет", "url": "u1"},   # дубль (text+url) → отбрасываем
        {"text": "", "url": "u2"},          # пустой текст → отбрасываем
        "не dict",                          # мусор → отбрасываем
    ]
    result = coerce_comment_examples(raw)
    assert len(result) == 1
    assert result[0]["text"] == "привет"
    assert result[0]["url"] == "u1"
    assert coerce_comment_examples("не список") == []


def test_legacy_comment_examples_dedups_across_groups():
    result = legacy_comment_examples(["жалоба", "жалоба"], ["просьба"])
    texts = [(e["text"], e["message_type"]) for e in result]
    assert ("жалоба", "complaint") in texts
    assert ("просьба", "request") in texts
    assert len(result) == 2  # дубль "жалоба" схлопнут


def test_append_comment_example_to_list_dedup_and_limit():
    items: list[dict] = []
    common = dict(
        message_type="complaint",
        sentiment=SentimentEnum.negative,
        publication_url="https://vk.com/wall-1_2",
        comment_external_id="1",
        comment_id=uuid.uuid4(),
    )
    append_comment_example_to_list(items, text="один и тот же", **common)
    append_comment_example_to_list(items, text="один и тот же", **common)  # дубль → игнор
    assert len(items) == 1
    assert items[0]["url"] == "https://vk.com/wall-1_2?reply=1"
    assert items[0]["sentiment"] == "negative"

    # лимит: добавляем уникальные до предела limit=5 (1 уже есть → ещё 4)
    for i in range(10):
        append_comment_example_to_list(
            items,
            text=f"уникальный {i}",
            message_type="complaint",
            sentiment=SentimentEnum.negative,
            publication_url="https://vk.com/wall-1_2",
            comment_external_id=str(100 + i),
            comment_id=uuid.uuid4(),
            limit=5,
        )
    assert len(items) == 5
