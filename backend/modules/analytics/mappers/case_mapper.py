"""Преобразование внутренних черновиков (``VkCaseDraft``/``VkSubproblemDraft``)
в pydantic-схемы ответа API (``StructuredCaseItem``/``StructuredSubproblemItem``).

Здесь нет бизнес-логики — только маппинг полей и сортировка дочерних
кейсов по числу упоминаний.
"""
from __future__ import annotations

from backend.modules.analytics.dtos.drafts import VkCaseDraft, VkSubproblemDraft
from backend.modules.analytics.schemas import SentimentBreakdown, MessageTypeBreakdown, StructuredCaseItem, \
    PainCommentExample, StructuredSubproblemItem


def to_sentiment_breakdown(values: dict[str, int]) -> SentimentBreakdown:
    """Конвертирует ``dict[str, int]`` в pydantic-схему тональности."""

    return SentimentBreakdown(
        positive=int(values.get("positive", 0)),
        neutral=int(values.get("neutral", 0)),
        negative=int(values.get("negative", 0)),
    )


def to_message_type_breakdown(values: dict[str, int]) -> MessageTypeBreakdown:
    """Конвертирует ``dict[str, int]`` в pydantic-схему типов сообщений."""

    return MessageTypeBreakdown(
        complaint=int(values.get("complaint", 0)),
        request=int(values.get("request", 0)),
        gratitude=int(values.get("gratitude", 0)),
        offtopic=int(values.get("offtopic", 0)),
        sarcasm=int(values.get("sarcasm", 0)),
    )


def case_to_payload(case_item: VkCaseDraft) -> StructuredCaseItem:
    """``VkCaseDraft`` → ``StructuredCaseItem`` для ответа API."""

    return StructuredCaseItem(
        title=case_item.title,
        raw_title=case_item.title,
        mentions_count=len(case_item.comment_ids),
        comment_examples=[
            PainCommentExample.model_validate(item)
            for item in case_item.comment_examples[:5]
        ],
        sentiment_counts=to_sentiment_breakdown(case_item.sentiment_counts),
        message_type_counts=to_message_type_breakdown(case_item.message_type_counts),
        request_count=case_item.request_count,
        complaint_count=case_item.complaint_count,
        source_urls=sorted(case_item.source_urls)[:5],
    )


def subproblem_to_payload(subproblem: VkSubproblemDraft) -> StructuredSubproblemItem:
    """``VkSubproblemDraft`` → ``StructuredSubproblemItem`` со вложенными кейсами."""

    return StructuredSubproblemItem(
        title=subproblem.title,
        description=None,
        mentions_count=len(subproblem.comment_ids),
        comment_examples=[
            PainCommentExample.model_validate(item)
            for item in subproblem.comment_examples[:5]
        ],
        sentiment_counts=to_sentiment_breakdown(subproblem.sentiment_counts),
        message_type_counts=to_message_type_breakdown(subproblem.message_type_counts),
        request_count=subproblem.request_count,
        complaint_count=subproblem.complaint_count,
        source_urls=sorted(subproblem.source_urls)[:5],
        cases=[
            case_to_payload(item)
            for _, item in sorted(
                subproblem.cases.items(),
                key=lambda pair: len(pair[1].comment_ids),
                reverse=True,
            )
        ],
    )
