"""Rule-based слой не должен делать болью нейтральное упоминание темы."""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from backend.db.comment_analysis import CommentAnalysis
from backend.db.enums import RelevanceEnum, SentimentEnum
from backend.modules.analytics.services.comment_analysis_service import (
    analysis_needs_refresh,
    apply_llm_analysis,
    apply_rule_based_analysis,
)


def _apply(text, *, sentiment, has_request, topics):
    analysis = CommentAnalysis()
    apply_rule_based_analysis(
        analysis,
        text=text,
        generated_at=datetime.now(timezone.utc),
        rule_topics=topics,
        rule_sentiment=sentiment,
        rule_has_request=has_request,
    )
    return analysis


def test_neutral_topic_mention_is_not_a_pain():
    # Театральный паблик: тема «дорога» мелькнула, но это не жалоба.
    analysis = _apply(
        "Ехали по дороге на спектакль, чудесный вечер",
        sentiment=SentimentEnum.neutral,
        has_request=False,
        topics={"roads"},
    )
    assert analysis.relevance == RelevanceEnum.irrelevant
    assert analysis.hierarchy["category"] == ""
    assert analysis.classification_source == "fallback"


def test_negative_topic_is_a_pain_needs_review():
    """Правила помечают боль relevant, но категорию НЕ ставят (ненадёжно ~44%):
    relevant без категории → needs_review, категорию доклассифицирует LLM."""
    analysis = _apply(
        "Дорога разбита, везде ямы",
        sentiment=SentimentEnum.negative,
        has_request=False,
        topics={"roads"},
    )
    assert analysis.relevance == RelevanceEnum.relevant
    assert analysis.hierarchy["category"] == ""
    assert analysis.classification_source == "needs_review"


def test_request_is_a_pain_even_without_negative():
    analysis = _apply(
        "Когда почистят дорогу?",
        sentiment=SentimentEnum.neutral,
        has_request=True,
        topics={"roads"},
    )
    assert analysis.relevance == RelevanceEnum.relevant


class _Dumpable(SimpleNamespace):
    def model_dump(self):
        return dict(self.__dict__)


def test_llm_relevant_without_category_becomes_terminal_review():
    analysis = CommentAnalysis()
    payload = SimpleNamespace(
        hierarchy=_Dumpable(category="", subcategory="", case=""),
        entities=_Dumpable(),
        sentiment="negative",
        is_official_response=False,
        author_type="citizen",
        message_type="complaint",
        relevance="relevant",
        summary="Неясная жалоба без категории",
    )

    apply_llm_analysis(
        analysis,
        payload=payload,
        generated_at=datetime.now(timezone.utc),
        source_text="Почему опять так плохо?",
    )

    assert analysis.classification_source == "llm_needs_review"
    assert analysis.hierarchy["category"] == ""
    assert analysis_needs_refresh(analysis) is False
