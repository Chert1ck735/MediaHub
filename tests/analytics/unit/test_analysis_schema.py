"""Схема constrained decoding: enum не должен разъезжаться с таксономией и промптом."""
from __future__ import annotations

import json
from pathlib import Path

from backend.modules.analytics.constants import CATEGORY_ALIASES
from backend.modules.llm.analysis_schema import (
    analysis_categories,
    build_analysis_json_schema,
)
from backend.modules.llm.schemas import CommentAnalysisResponse

_PROMPT = (
    Path(__file__).resolve().parents[3]
    / "backend/modules/llm/prompts/analysis/system.md"
)


def _category_enum() -> list[str]:
    schema = build_analysis_json_schema()
    return schema["properties"]["hierarchy"]["properties"]["category"]["enum"]


def test_categories_come_from_taxonomy():
    assert analysis_categories() == tuple(CATEGORY_ALIASES)


def test_schema_is_json_serializable():
    json.dumps(build_analysis_json_schema())


def test_category_enum_allows_empty_and_every_taxonomy_value():
    enum = _category_enum()

    assert enum[0] == ""  # шум без категории — легальный ответ
    for category in CATEGORY_ALIASES:
        assert category in enum


def test_prompt_lists_the_same_categories_as_schema():
    """Промпт и enum должны описывать одну таксономию, иначе модель в тупике."""

    prompt = _PROMPT.read_text(encoding="utf-8")

    for category in CATEGORY_ALIASES:
        assert category in prompt, f"категории {category!r} нет в промпте"


def test_schema_forbids_extra_keys():
    schema = build_analysis_json_schema()

    assert schema["additionalProperties"] is False
    assert schema["properties"]["hierarchy"]["additionalProperties"] is False


def test_confidence_and_candidates_are_required():
    schema = build_analysis_json_schema()

    assert "confidence" in schema["required"]
    assert "candidates" in schema["required"]


def test_response_model_tolerates_missing_confidence_fields():
    """Парсинг остаётся мягким: старый ответ без confidence не должен падать."""

    payload = {
        "relevance": "relevant",
        "author_type": "citizen",
        "message_type": "complaint",
        "sentiment": "negative",
        "is_official_response": False,
        "hierarchy": {"category": "Дороги и транспорт", "subcategory": "", "case": ""},
        "entities": {
            "address": None,
            "institution": None,
            "reference_number": None,
            "deadline": None,
        },
        "summary": "яма на дороге",
    }

    parsed = CommentAnalysisResponse.model_validate(payload)

    assert parsed.confidence == 0.5
    assert parsed.candidates == []


def test_response_model_accepts_unknown_category():
    """Схема ограничивает генерацию, но парсер обязан пережить чужой ответ."""

    payload = {
        "relevance": "relevant",
        "author_type": "citizen",
        "message_type": "complaint",
        "sentiment": "negative",
        "is_official_response": False,
        "hierarchy": {"category": "Выдуманная", "subcategory": "", "case": ""},
        "entities": {
            "address": None,
            "institution": None,
            "reference_number": None,
            "deadline": None,
        },
        "summary": "",
        "confidence": 0.3,
        "candidates": [{"category": "Другое", "subcategory": "", "confidence": 0.2}],
    }

    parsed = CommentAnalysisResponse.model_validate(payload)

    assert parsed.hierarchy.category == "Выдуманная"
    assert parsed.candidates[0].confidence == 0.2
