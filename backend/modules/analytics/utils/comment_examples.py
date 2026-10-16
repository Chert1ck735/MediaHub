"""Сбор и нормализация примеров комментариев для отображения в боли/кейсе."""
from __future__ import annotations

import uuid
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
from typing import Any

from backend.db.enums import SentimentEnum
from backend.modules.analytics.dtos.drafts import VkPainDraft
from backend.modules.analytics.schemas import PainCommentExample
from backend.modules.analytics.utils.text_normalize import trim_text


def comment_example_from_string(
    text: str,
    message_type: str | None = None,
) -> dict[str, Any]:
    """Оборачивает голую строку комментария в payload с пустой обвязкой."""

    return {
        "text": trim_text(text, 320),
        "url": None,
        "publication_url": None,
        "comment_id": None,
        "message_type": message_type,
        "sentiment": None,
    }


def coerce_comment_examples(raw_examples: Any) -> list[dict[str, Any]]:
    """Приводит произвольный вход (список dict / pydantic-объектов) к dict-payload'ам."""

    normalized: list[dict[str, Any]] = []
    seen: set[tuple[str, str | None]] = set()
    if not isinstance(raw_examples, list):
        return normalized

    for raw in raw_examples:
        if isinstance(raw, PainCommentExample):
            payload = raw.model_dump(mode="json")
        elif isinstance(raw, dict):
            payload = raw
        else:
            continue

        text = trim_text(str(payload.get("text") or ""), 320)
        if not text:
            continue
        url = str(payload.get("url") or "").strip() or None
        publication_url = str(payload.get("publication_url") or "").strip() or None
        key = (text, url or publication_url)
        if key in seen:
            continue
        seen.add(key)
        normalized.append(
            {
                "text": text,
                "url": url,
                "publication_url": publication_url,
                "comment_id": str(payload.get("comment_id") or "").strip() or None,
                "message_type": str(payload.get("message_type") or "").strip() or None,
                "sentiment": str(payload.get("sentiment") or "").strip() or None,
            }
        )
    return normalized


def legacy_comment_examples(
    complaint_examples: list[str],
    request_examples: list[str],
) -> list[dict[str, Any]]:
    """Конвертирует пары списков (жалобы/запросы) из старой схемы в новый формат."""

    examples: list[dict[str, Any]] = []
    seen: set[str] = set()
    for message_type, items in (
        ("complaint", complaint_examples),
        ("request", request_examples),
    ):
        for item in items:
            text = trim_text(item, 320)
            if not text or text in seen:
                continue
            seen.add(text)
            examples.append(comment_example_from_string(text, message_type))
    return examples


def vk_comment_url(
    publication_url: str | None,
    comment_external_id: str | None,
) -> str | None:
    """Собирает URL комментария ВК на основе ссылки публикации и id комментария."""

    base_url = (publication_url or "").strip()
    comment_id = (comment_external_id or "").strip()
    if not base_url:
        return None
    if not comment_id:
        return base_url
    parts = urlsplit(base_url)
    host = (parts.hostname or "").lower().removeprefix("www.")
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    if host in ("t.me", "telegram.me"):
        query.setdefault("comment", comment_id.rsplit(":", 1)[-1])
    elif host in ("vk.com", "m.vk.com", "vk.ru"):
        query.setdefault("reply", comment_id)
    else:
        return base_url
    return urlunsplit(parts._replace(query=urlencode(query)))


def append_comment_example(
    bucket: VkPainDraft,
    *,
    text: str,
    message_type: str,
    sentiment: SentimentEnum,
    publication_url: str | None,
    comment_external_id: str | None,
    comment_id: uuid.UUID,
) -> None:
    """Добавляет пример комментария к боли (не более 6 уникальных)."""

    normalized_text = trim_text(text, 320)
    if not normalized_text:
        return
    url = vk_comment_url(publication_url, comment_external_id)
    key = (normalized_text, url or publication_url or "")
    existing_keys = {
        (
            str(item.get("text") or "").strip(),
            str(item.get("url") or item.get("publication_url") or "").strip(),
        )
        for item in bucket.comment_examples
    }
    if key in existing_keys or len(bucket.comment_examples) >= 25:
        return
    bucket.comment_examples.append(
        {
            "text": normalized_text,
            "url": url,
            "publication_url": publication_url,
            "comment_id": str(comment_id),
            "message_type": message_type,
            "sentiment": sentiment.value,
        }
    )


def append_comment_example_to_list(
    items: list[dict[str, Any]],
    *,
    text: str,
    message_type: str,
    sentiment: SentimentEnum,
    publication_url: str | None,
    comment_external_id: str | None,
    comment_id: uuid.UUID,
    limit: int = 5,
) -> None:
    """Универсальный вариант ``append_comment_example`` для произвольного списка."""

    normalized_text = trim_text(text, 320)
    if not normalized_text:
        return
    url = vk_comment_url(publication_url, comment_external_id)
    existing_keys = {
        (
            str(item.get("text") or "").strip(),
            str(item.get("url") or item.get("publication_url") or "").strip(),
        )
        for item in items
    }
    key = (normalized_text, url or publication_url or "")
    if key in existing_keys or len(items) >= limit:
        return
    items.append(
        {
            "text": normalized_text,
            "url": url,
            "publication_url": publication_url,
            "comment_id": str(comment_id),
            "message_type": message_type,
            "sentiment": sentiment.value,
        }
    )
