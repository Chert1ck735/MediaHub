"""Характеристик-тесты на детерминированные rule-based хелперы analytics."""
from __future__ import annotations

from backend.db.enums import RelevanceEnum, SentimentEnum
from backend.modules.analytics.constants import CATEGORY_ALIASES
from backend.modules.analytics.utils.text_normalize import (
    append_unique,
    match_alias,
    normalized_lookup_text,
    string_dict,
    trim_text,
)
from backend.modules.analytics.utils.sentiment_rules import (
    fallback_relevance,
    has_request_signal,
    looks_sarcastic,
    rule_category_from_topics,
    sentiment_for_text,
    topics_for_text,
)
from backend.modules.analytics.utils.official_response import (
    is_community_authored,
    looks_like_official_response,
)


# ─────────────────────────── text_normalize ───────────────────────────

def test_trim_text_collapses_whitespace_and_truncates():
    assert trim_text("  привет   мир  ") == "привет мир"
    assert trim_text("a" * 300) == "a" * 240
    assert trim_text("слово", limit=3) == "сло"


def test_normalized_lookup_text_lowercases_and_replaces_yo():
    assert normalized_lookup_text("ПодъЁЗД  Тёплый") == "подъезд теплый"
    assert normalized_lookup_text("") == ""


def test_match_alias_finds_canonical_key():
    # "дорог" — алиас категории "Дороги и транспорт".
    assert match_alias("дороги плохие", CATEGORY_ALIASES) == "Дороги и транспорт"
    # Нет пересечений ни с одним алиасом.
    assert match_alias("zzz", CATEGORY_ALIASES) is None
    assert match_alias("", CATEGORY_ALIASES) is None


def test_append_unique_dedups_and_respects_limit():
    items: list[str] = []
    append_unique(items, "a", limit=2)
    append_unique(items, "a", limit=2)  # дубль — игнор
    append_unique(items, "   ", limit=2)  # пусто — игнор
    append_unique(items, "b", limit=2)
    append_unique(items, "c", limit=2)  # лимит достигнут — игнор
    assert items == ["a", "b"]


def test_string_dict_filters_non_str_keys_and_none_values():
    result = string_dict({"a": 1, "b": None, 3: "x", "c": " y "})
    assert result == {"a": "1", "c": "y"}
    assert string_dict("not a dict") == {}


# ─────────────────────────── sentiment_rules ───────────────────────────

def test_topics_for_text_detects_known_topics():
    assert "roads" in topics_for_text("дорога вся разбита")
    assert "housing" in topics_for_text("нет отопления в доме")
    assert topics_for_text("просто нейтральный текст без триггеров") == set()


def test_sentiment_for_text_balance():
    assert sentiment_for_text("спасибо большое за работу") == SentimentEnum.positive
    assert sentiment_for_text("это ужас, везде ямы") == SentimentEnum.negative
    assert sentiment_for_text("обычное сообщение") == SentimentEnum.neutral
    assert sentiment_for_text("") == SentimentEnum.neutral


def test_has_request_signal():
    assert has_request_signal("Прошу помочь с этим") is True
    assert has_request_signal("Почему так долго?") is True
    assert has_request_signal("просто комментарий") is False


def test_looks_sarcastic_when_positive_and_negative_mix():
    assert looks_sarcastic("спасибо за такой ужас на дорогах") is True
    assert looks_sarcastic("дорога разбита") is False


def test_fallback_relevance():
    # Запрос — всегда релевантно.
    assert fallback_relevance(set(), True) == RelevanceEnum.relevant
    # Тема + негатив (жалоба) — релевантно.
    assert fallback_relevance({"roads"}, False, SentimentEnum.negative) == RelevanceEnum.relevant
    # Тема без негатива и без запроса — НЕ боль (нейтральное упоминание).
    assert fallback_relevance({"roads"}, False) == RelevanceEnum.irrelevant
    assert fallback_relevance({"roads"}, False, SentimentEnum.neutral) == RelevanceEnum.irrelevant
    assert fallback_relevance({"roads"}, False, SentimentEnum.positive) == RelevanceEnum.irrelevant
    # Совсем нет сигналов.
    assert fallback_relevance(set(), False) == RelevanceEnum.irrelevant


def test_rule_category_from_topics():
    assert rule_category_from_topics({"roads"}) == "Дороги и транспорт"
    assert rule_category_from_topics(set()) == ""


# ─────────────────────────── official_response ───────────────────────────

def test_is_community_authored_detects_negative_from_id():
    assert is_community_authored("-12345") is True
    assert is_community_authored("  -12345 ") is True
    assert is_community_authored("12345") is False
    assert is_community_authored(None) is False
    assert is_community_authored("") is False


def test_looks_like_official_response_moderation_token():
    assert looks_like_official_response("Спасибо за ваш вопрос, ответим после эфира") is True


def test_looks_like_official_response_by_author_name():
    assert looks_like_official_response("любой текст", author_name="Администрация района") is True


def test_looks_like_official_response_plain_citizen_comment():
    assert looks_like_official_response("Дорога разбита, когда почините?") is False


def test_vk_mention_only_is_not_meaningful_official_response():
    from backend.modules.analytics.utils.official_response import is_meaningful_official_response

    assert is_meaningful_official_response("[id3546786543|Надежда],") is False
    assert is_meaningful_official_response("[club123|Администрация], добрый день!") is True


def test_citizen_polite_address_is_not_official():
    assert looks_like_official_response(
        "Уважаемый Михаил Викторович, у нас во дворе прорвало трубу, помогите!"
    ) is False
