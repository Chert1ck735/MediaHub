"""Уверенность модели вместо константы: она питает needs_review и candidates."""
from __future__ import annotations

from datetime import datetime, timezone

from backend.app.config import settings
from backend.db.comment_analysis import CommentAnalysis
from backend.db.enums import RelevanceEnum
from backend.modules.analytics.services.comment_analysis_service import apply_llm_analysis
from backend.modules.llm.schemas import CommentAnalysisResponse

_NOW = datetime(2026, 7, 21, tzinfo=timezone.utc)


def _payload(**overrides) -> CommentAnalysisResponse:
    base = {
        "relevance": "relevant",
        "author_type": "citizen",
        "message_type": "complaint",
        "sentiment": "negative",
        "is_official_response": False,
        "hierarchy": {
            "category": "Дороги и транспорт",
            "subcategory": "качество дорог",
            "case": "ул. Ленина, 5",
        },
        "entities": {
            "address": None,
            "institution": None,
            "reference_number": None,
            "deadline": None,
        },
        "summary": "яма",
        "confidence": 0.95,
        "candidates": [],
    }
    base.update(overrides)
    return CommentAnalysisResponse.model_validate(base)


def _apply(payload: CommentAnalysisResponse, text: str = "Яма на ул. Ленина, 5") -> CommentAnalysis:
    analysis = CommentAnalysis(comment_id=None)
    apply_llm_analysis(analysis, payload=payload, generated_at=_NOW, source_text=text)
    return analysis


def test_confidence_taken_from_model_not_constant():
    analysis = _apply(_payload(confidence=0.72))

    assert analysis.confidence == 0.72


def test_low_confidence_marks_needs_review():
    low = settings.LLM_LOW_CONFIDENCE_THRESHOLD - 0.1
    analysis = _apply(_payload(confidence=low))

    assert analysis.needs_review is True


def test_high_confidence_does_not_mark_needs_review():
    analysis = _apply(_payload(confidence=0.95))

    assert analysis.needs_review is False


def test_candidates_are_persisted():
    analysis = _apply(
        _payload(
            candidates=[
                {"category": "ЖКХ и городская среда", "subcategory": "", "confidence": 0.3},
            ]
        )
    )

    assert analysis.candidates == [
        {"category": "ЖКХ и городская среда", "subcategory": "", "confidence": 0.3}
    ]


def test_irrelevant_never_goes_to_review():
    """У шума низкая уверенность ничего не решает — ревью там бессмысленно."""

    analysis = _apply(
        _payload(
            relevance="irrelevant",
            message_type="offtopic",
            confidence=0.1,
            hierarchy={"category": "", "subcategory": "", "case": ""},
        ),
        text="спасибо",
    )

    assert analysis.relevance == RelevanceEnum.irrelevant
    assert analysis.needs_review is False
