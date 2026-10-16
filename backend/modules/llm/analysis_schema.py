"""JSON Schema разбора комментария для constrained decoding.

Схема описана руками, а не выведена из pydantic-модели, потому что у неё другая
задача. Pydantic **принимает** ответ и намеренно мягок: неизвестная категория
переживается и чинится нормализацией ниже по потоку. Эта же схема **ограничивает
генерацию**: пока модель пишет ответ, рантайм не даёт ей выйти за enum, поэтому
здесь перечислены точные значения, а `additionalProperties` запрещены.

Категории берём из ``CATEGORY_ALIASES`` — единственного источника таксономии,
чтобы enum, промпт и нормализация не разъезжались.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Any


@lru_cache(maxsize=1)
def analysis_categories() -> tuple[str, ...]:
    """Канонический список категорий из таксономии аналитики.

    Импорт отложенный: пакет ``backend.modules.analytics`` в ``__init__``
    поднимает роутер, который через classification тянет обратно этот модуль.
    На уровне модуля это замкнуло бы цикл, а к моменту вызова всё уже собрано.
    """

    from backend.modules.analytics.constants import CATEGORY_ALIASES

    # Порядок сохраняем как в таксономии — он же в промпте.
    return tuple(CATEGORY_ALIASES)

RELEVANCE_VALUES: tuple[str, ...] = ("relevant", "irrelevant")
AUTHOR_TYPE_VALUES: tuple[str, ...] = ("citizen", "admin", "official")
MESSAGE_TYPE_VALUES: tuple[str, ...] = (
    "complaint",
    "request",
    "gratitude",
    "offtopic",
    "sarcasm",
)
SENTIMENT_VALUES: tuple[str, ...] = ("positive", "neutral", "negative")

SCHEMA_NAME = "comment_analysis"


def _nullable_string() -> dict[str, Any]:
    return {"type": ["string", "null"]}


def build_analysis_json_schema() -> dict[str, Any]:
    """Схема ответа классификатора комментариев."""

    categories = analysis_categories()
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "relevance",
            "author_type",
            "message_type",
            "sentiment",
            "is_official_response",
            "hierarchy",
            "entities",
            "summary",
            "confidence",
            "candidates",
        ],
        "properties": {
            "relevance": {"type": "string", "enum": list(RELEVANCE_VALUES)},
            "author_type": {"type": "string", "enum": list(AUTHOR_TYPE_VALUES)},
            "message_type": {"type": "string", "enum": list(MESSAGE_TYPE_VALUES)},
            "sentiment": {"type": "string", "enum": list(SENTIMENT_VALUES)},
            "is_official_response": {"type": "boolean"},
            "hierarchy": {
                "type": "object",
                "additionalProperties": False,
                "required": ["category", "subcategory", "case"],
                "properties": {
                    # Пустая строка — легальный ответ: у шума категории нет.
                    "category": {
                        "type": "string",
                        "enum": ["", *categories],
                    },
                    "subcategory": {"type": "string"},
                    "case": {"type": "string"},
                },
            },
            "entities": {
                "type": "object",
                "additionalProperties": False,
                "required": ["address", "institution", "reference_number", "deadline"],
                "properties": {
                    "address": _nullable_string(),
                    "institution": _nullable_string(),
                    "reference_number": _nullable_string(),
                    "deadline": _nullable_string(),
                },
            },
            "summary": {"type": "string"},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "candidates": {
                "type": "array",
                "maxItems": 2,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["category", "subcategory", "confidence"],
                    "properties": {
                        "category": {
                            "type": "string",
                            "enum": ["", *categories],
                        },
                        "subcategory": {"type": "string"},
                        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    },
                },
            },
        },
    }


__all__ = [
    "analysis_categories",
    "SCHEMA_NAME",
    "build_analysis_json_schema",
]
