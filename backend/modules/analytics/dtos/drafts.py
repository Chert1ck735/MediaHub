"""Промежуточные структуры для агрегации комментариев VK в боли и кейсы.

Эти dataclass-ы накапливают данные во время прохода по комментариям
(в `vk_snapshot_service`) и затем сериализуются в pydantic-схемы через
`mappers.case_mapper`. В БД они не записываются и над ними не строится
бизнес-логика — это чистые контейнеры данных.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any


def _empty_sentiment_counts() -> dict[str, int]:
    return {"positive": 0, "neutral": 0, "negative": 0}


def _empty_message_type_counts() -> dict[str, int]:
    return {
        "complaint": 0,
        "request": 0,
        "gratitude": 0,
        "offtopic": 0,
        "sarcasm": 0,
    }


@dataclass
class VkCaseDraft:
    """Адресный кейс внутри подпроблемы — например, конкретный дом или маршрут."""

    title: str
    comment_ids: set[uuid.UUID] = field(default_factory=set)
    publication_ids: set[uuid.UUID] = field(default_factory=set)
    comment_examples: list[dict[str, Any]] = field(default_factory=list)
    source_urls: set[str] = field(default_factory=set)
    sentiment_counts: dict[str, int] = field(default_factory=_empty_sentiment_counts)
    message_type_counts: dict[str, int] = field(default_factory=_empty_message_type_counts)
    request_count: int = 0
    complaint_count: int = 0


@dataclass
class VkSubproblemDraft:
    """Подпроблема внутри боли — например, конкретная улица или категория."""

    title: str
    comment_ids: set[uuid.UUID] = field(default_factory=set)
    publication_ids: set[uuid.UUID] = field(default_factory=set)
    comment_examples: list[dict[str, Any]] = field(default_factory=list)
    source_urls: set[str] = field(default_factory=set)
    sentiment_counts: dict[str, int] = field(default_factory=_empty_sentiment_counts)
    message_type_counts: dict[str, int] = field(default_factory=_empty_message_type_counts)
    request_count: int = 0
    complaint_count: int = 0
    cases: dict[str, VkCaseDraft] = field(default_factory=dict)


@dataclass
class VkPainDraft:
    """Боль верхнего уровня — например, «ЖКХ», «Дороги», «Безопасность»."""

    topic: str
    title: str
    category: str
    comment_ids: set[uuid.UUID] = field(default_factory=set)
    public_ids: set[uuid.UUID] = field(default_factory=set)
    publication_ids: set[uuid.UUID] = field(default_factory=set)
    subproblems: set[str] = field(default_factory=set)
    evidence: list[dict[str, Any]] = field(default_factory=list)
    requests: list[str] = field(default_factory=list)
    negative_points: list[str] = field(default_factory=list)
    positive_signals: list[str] = field(default_factory=list)
    comment_examples: list[dict[str, Any]] = field(default_factory=list)
    sentiment_counts: dict[str, int] = field(default_factory=_empty_sentiment_counts)
    message_type_counts: dict[str, int] = field(default_factory=_empty_message_type_counts)
    request_count: int = 0
    complaint_count: int = 0
    subproblem_items: dict[str, VkSubproblemDraft] = field(default_factory=dict)

    # Дедупликация одной агитки, повторённой в N комментариях. Без этого
    # упоминания боли раздуваются на копипасте.
    seen_text_hashes: set[str] = field(default_factory=set)

    # Гистограмма часов комментариев — для рекомендации лучшего времени поста.
    hourly_histogram: dict[int, int] = field(default_factory=dict)
