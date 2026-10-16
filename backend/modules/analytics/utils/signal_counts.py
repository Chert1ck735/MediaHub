"""Счётчики тональности и типов сообщений для агрегаций.

Используются в `pain_aggregation`/`case_builder` при проходе по
комментариям: один комментарий — один инкремент.
"""
from __future__ import annotations

from backend.db.enums import SentimentEnum


def empty_sentiment_counts() -> dict[str, int]:
    """Возвращает шаблон счётчиков тональности (positive/neutral/negative)."""

    return {"positive": 0, "neutral": 0, "negative": 0}


def empty_message_type_counts() -> dict[str, int]:
    """Возвращает шаблон счётчиков типов сообщений (complaint/request/...)."""

    return {
        "complaint": 0,
        "request": 0,
        "gratitude": 0,
        "offtopic": 0,
        "sarcasm": 0,
    }


def bump_signal_counts(
    sentiment_counts: dict[str, int],
    message_type_counts: dict[str, int],
    *,
    sentiment: SentimentEnum,
    message_type: str,
) -> None:
    """Инкрементирует счётчики тональности и типа сообщения in-place."""

    sentiment_counts[sentiment.value] = sentiment_counts.get(sentiment.value, 0) + 1
    if message_type in message_type_counts:
        message_type_counts[message_type] = message_type_counts.get(message_type, 0) + 1
