"""
Подготовка и нормализация payload-ов аналитики.

Здесь живёт работа с *уже сохранённым* ``AnalysisSnapshot.raw_payload``:
  * приведение legacy-формата к каноническому ``StructuredPainAnalyticsPayload``;
  * сборка контекста для конкретной боли (из структурированной части или
    через эвристический fallback);
  * мелкие текстовые трансформации стратегий.

Чистая логика над pydantic-схемами — без БД и без LLM.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from backend.db.analysis_snapshots import AnalysisSnapshot
from backend.db.pains import Pain
from backend.modules.analytics.schemas import StructuredPainAnalyticsPayload, StructuredPainStrategy, \
    StructuredPainItem, LegacyGlobalProblemPayload
from backend.modules.analytics.utils.case_extractor import infer_category
from backend.modules.analytics.utils.category_classifier import match_solution
from backend.modules.analytics.utils.comment_examples import (
    coerce_comment_examples,
    legacy_comment_examples,
)
from backend.modules.analytics.utils.sentiment_rules import (
    select_related_items,
    topics_for_pain,
)
from backend.modules.analytics.utils.severity_rules import (
    normalize_priority,
    severity_from_mentions,
)
from backend.modules.analytics.utils.signal_counts import (
    empty_message_type_counts,
    empty_sentiment_counts,
)

def fallback_pain_context(
    normalized: StructuredPainAnalyticsPayload,
    pain_title: str,
    category: str | None,
) -> dict[str, Any]:
    """Эвристический контекст боли, когда структурированный payload пустой."""

    pain_topics = topics_for_pain(pain_title, category)
    fallback: dict[str, Any] = {
        "citizens_requests": select_related_items(
            normalized.citizens_requests,
            pain_topics,
            include_governance_for_all=True,
        ),
        "dissatisfaction_points": select_related_items(
            normalized.dissatisfaction_points,
            pain_topics,
            include_governance_for_all=True,
        ),
        "positive_signals": select_related_items(normalized.satisfaction_points, pain_topics),
        "risk_zones": select_related_items(normalized.risk_zones, pain_topics),
        "quick_wins_30_days": select_related_items(normalized.quick_wins_30_days, pain_topics),
        "strategic_actions_3_6_months": select_related_items(
            normalized.strategic_actions_3_6_months,
            pain_topics,
            include_governance_for_all=True,
        ),
    }
    fallback["comment_examples"] = legacy_comment_examples(
        list(fallback["dissatisfaction_points"]),
        list(fallback["citizens_requests"]),
    )
    fallback["sentiment_counts"] = empty_sentiment_counts()
    fallback["message_type_counts"] = empty_message_type_counts()
    fallback["request_count"] = len(fallback["citizens_requests"])
    fallback["complaint_count"] = len(fallback["dissatisfaction_points"])
    fallback["subproblems"] = []
    fallback["subproblem_items"] = []
    fallback["communication_strategy"] = None
    fallback["subcategory"] = None
    fallback["publications_count"] = 0
    return fallback


def clean_strategy_text(value: str) -> str:
    """Удаляет служебные строки вида ``priority:`` из текста стратегии."""

    lines: list[str] = []
    for raw_line in value.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        low = line.lower()
        if low.startswith("priority:") or low.startswith("приоритет:"):
            continue
        lines.append(raw_line)
    return "\n".join(lines).strip()


def strategy_to_description(strategy: StructuredPainStrategy) -> str:
    """Собирает список действий в bullet-формат для хранения в БД."""

    return "\n".join(f"- {action}" for action in strategy.actions).strip()


def infer_snapshot_source_type(source_name: str, source_format: str) -> str:
    """Угадывает источник данных по имени и формату (``excel``/``vk``/...)."""

    fingerprint = f"{source_name} {source_format}".lower()
    if any(token in fingerprint for token in ("excel", "sheet", "csv", "xlsx")):
        return "excel"
    if any(token in fingerprint for token in ("vk", "vkontakte", "вконтакте")):
        return "vk"
    return source_name or "unknown"


def build_pain_context(snapshot: AnalysisSnapshot, pain: Pain) -> dict[str, Any]:
    """Собирает контекст для отдельной боли — со structured-приоритетом и fallback'ом."""

    normalized = StructuredPainAnalyticsPayload.model_validate(snapshot.raw_payload)
    matching_item = next((item for item in normalized.pains if item.title == pain.title), None)
    if matching_item:
        comment_examples = coerce_comment_examples(matching_item.comment_examples)
        if not comment_examples:
            comment_examples = legacy_comment_examples(
                matching_item.complaint_examples or matching_item.dissatisfaction_points,
                matching_item.request_examples or matching_item.citizens_requests,
            )
        structured_context = {
            "citizens_requests": matching_item.citizens_requests,
            "dissatisfaction_points": matching_item.dissatisfaction_points,
            "positive_signals": matching_item.positive_signals,
            "sentiment_counts": (
                matching_item.sentiment_counts.model_dump()
                if hasattr(matching_item.sentiment_counts, "model_dump")
                else dict(matching_item.sentiment_counts or {})
            ),
            "message_type_counts": (
                matching_item.message_type_counts.model_dump()
                if hasattr(matching_item.message_type_counts, "model_dump")
                else dict(matching_item.message_type_counts or {})
            ),
            "request_count": matching_item.request_count,
            "complaint_count": matching_item.complaint_count,
            "risk_zones": [],
            "quick_wins_30_days": [],
            "strategic_actions_3_6_months": [],
            "comment_examples": comment_examples,
            "subproblems": matching_item.subproblems,
            "subproblem_items": [item.model_dump(mode="json") for item in matching_item.subproblem_items],
            "communication_strategy": matching_item.communication_strategy,
            "subcategory": matching_item.subcategory,
            "publications_count": matching_item.publications_count,
        }
        if any(structured_context.values()):
            return structured_context
    return fallback_pain_context(normalized, pain.title, pain.category)


def normalize_payload(
    source_name: str,
    payload: dict[str, Any],
) -> StructuredPainAnalyticsPayload:
    """Приводит сырой payload к каноническому ``StructuredPainAnalyticsPayload``.

    Поддерживает два формата:
      * новый — с ключом ``pains``: принимается как есть, дозаполняется
        ``source_name`` и ``generated_at``;
      * legacy — ``top_global_problems`` + ``possible_solutions``:
        конвертируется в новый, для каждого пункта собирается fallback-
        контекст и при возможности подтягивается стратегия.
    """

    if "pains" in payload:
        structured = StructuredPainAnalyticsPayload.model_validate(
            {
                **payload,
                "source_name": payload.get("source_name") or source_name,
            }
        )
        if structured.generated_at is None:
            structured.generated_at = datetime.now(timezone.utc)
        return structured

    legacy = LegacyGlobalProblemPayload.model_validate(payload)
    pains: list[StructuredPainItem] = []
    raw_solutions = [item.model_dump() for item in legacy.possible_solutions]
    legacy_to_structured = StructuredPainAnalyticsPayload(
        source_name=source_name,
        generated_at=datetime.now(timezone.utc),
        global_summary=legacy.global_summary,
        citizens_requests=legacy.citizens_requests,
        dissatisfaction_points=legacy.dissatisfaction_points,
        satisfaction_points=legacy.satisfaction_points,
        risk_zones=legacy.risk_zones,
        quick_wins_30_days=legacy.quick_wins_30_days,
        strategic_actions_3_6_months=legacy.strategic_actions_3_6_months,
        pains=[],
    )

    for item in legacy.top_global_problems:
        matched = match_solution(item.problem, raw_solutions)
        strategy: StructuredPainStrategy | None = None
        derived_priority = severity_from_mentions(item.frequency_estimate)
        fallback_context = fallback_pain_context(
            legacy_to_structured,
            item.problem,
            infer_category(item.problem),
        )
        if matched:
            derived_priority = normalize_priority(matched.get("priority")) or derived_priority
            strategy = StructuredPainStrategy(
                priority=matched.get("priority"),
                actions=list(matched.get("solutions", [])),
            )
        pains.append(
            StructuredPainItem(
                title=item.problem,
                description=None,
                category=infer_category(item.problem),
                mentions_count=item.frequency_estimate,
                severity_level=derived_priority,
                status="active",
                citizens_requests=fallback_context["citizens_requests"],
                dissatisfaction_points=fallback_context["dissatisfaction_points"],
                positive_signals=fallback_context["positive_signals"],
                comment_examples=fallback_context["comment_examples"],
                risk_zones=fallback_context["risk_zones"],
                quick_wins_30_days=fallback_context["quick_wins_30_days"],
                strategic_actions_3_6_months=fallback_context["strategic_actions_3_6_months"],
                evidence_posts=item.evidence_posts,
                strategy=strategy,
            )
        )

    return StructuredPainAnalyticsPayload(
        source_name=source_name,
        generated_at=datetime.now(timezone.utc),
        global_summary=legacy.global_summary,
        citizens_requests=legacy.citizens_requests,
        dissatisfaction_points=legacy.dissatisfaction_points,
        satisfaction_points=legacy.satisfaction_points,
        risk_zones=legacy.risk_zones,
        quick_wins_30_days=legacy.quick_wins_30_days,
        strategic_actions_3_6_months=legacy.strategic_actions_3_6_months,
        pains=pains,
    )
