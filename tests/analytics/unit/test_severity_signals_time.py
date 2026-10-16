"""Характеристик-тесты: severity_rules, signal_counts, time_helpers (без БД)."""
from __future__ import annotations

from datetime import datetime, timezone

from backend.db.enums import SentimentEnum
from backend.modules.analytics.utils.severity_rules import (
    normalize_priority,
    severity_from_mentions,
)
from backend.modules.analytics.utils.signal_counts import (
    bump_signal_counts,
    empty_message_type_counts,
    empty_sentiment_counts,
)
from backend.modules.analytics.utils.time_helpers import (
    format_post_window,
    period_to_since,
)


# ─────────────────────────── severity_rules ───────────────────────────

def test_severity_from_mentions_thresholds():
    assert severity_from_mentions(50) == "critical"
    assert severity_from_mentions(49) == "high"
    assert severity_from_mentions(20) == "high"
    assert severity_from_mentions(8) == "medium"
    assert severity_from_mentions(7) == "low"
    assert severity_from_mentions(0) == "low"


def test_normalize_priority():
    assert normalize_priority("HIGH ") == "high"
    assert normalize_priority("critical") == "critical"
    assert normalize_priority("bogus") is None
    assert normalize_priority("") is None
    assert normalize_priority(None) is None


# ─────────────────────────── signal_counts ───────────────────────────

def test_empty_counts_templates():
    assert empty_sentiment_counts() == {"positive": 0, "neutral": 0, "negative": 0}
    assert empty_message_type_counts() == {
        "complaint": 0,
        "request": 0,
        "gratitude": 0,
        "offtopic": 0,
        "sarcasm": 0,
    }


def test_bump_signal_counts_increments_known_keys():
    sent = empty_sentiment_counts()
    msg = empty_message_type_counts()
    bump_signal_counts(sent, msg, sentiment=SentimentEnum.negative, message_type="complaint")
    assert sent["negative"] == 1
    assert msg["complaint"] == 1


def test_bump_signal_counts_ignores_unknown_message_type():
    sent = empty_sentiment_counts()
    msg = empty_message_type_counts()
    bump_signal_counts(sent, msg, sentiment=SentimentEnum.positive, message_type="unknown_type")
    assert sent["positive"] == 1
    # неизвестный тип сообщения не создаёт новый ключ
    assert sum(msg.values()) == 0


# ─────────────────────────── time_helpers ───────────────────────────

def test_period_to_since_known_and_unknown():
    assert period_to_since(None) is None
    assert period_to_since("") is None
    assert period_to_since("bogus") is None
    week = period_to_since("week")
    assert week is not None and week.tzinfo is not None
    today = period_to_since("today")
    assert today is not None
    assert today.hour == 0
    assert today.minute == 0
    assert today.date() == datetime.now(timezone.utc).date()
    three_days = period_to_since("3days")
    assert three_days is not None
    three_days_delta = (datetime.now(timezone.utc) - three_days).days
    assert 2 <= three_days_delta <= 3
    # «месяц» и «month» дают одинаковый cutoff-порядок (~30 дней назад)
    month = period_to_since("месяц")
    delta_days = (datetime.now(timezone.utc) - month).days
    assert 29 <= delta_days <= 31


def test_format_post_window():
    assert format_post_window([], []) is None
    result = format_post_window([(9, 5), (10, 3), (11, 2)], [(2, 4), (4, 3)])
    assert result is not None
    assert result.startswith("9")
    assert "утра" in result
    assert "вт/чт" in result
