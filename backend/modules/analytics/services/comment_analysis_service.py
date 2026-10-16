"""Заполнение `CommentAnalysis` по результатам rule-based и LLM-разбора.

Слой между «сырыми» результатами анализа (правила-эвристики или LLM)
и сохраняемой ORM-моделью. Здесь:

  * ``apply_rule_based_analysis`` — заполняет поля по правилам/keywords,
    выводит ``message_type`` и ``classification_source``;
  * ``apply_llm_analysis`` — нормализует иерархию категорий из LLM-payload
    и проставляет ``classification_source`` (``llm`` / ``llm_other`` /
    ``llm_needs_review`` / ``llm_manual`` / ``fallback``);
  * ``analysis_needs_refresh`` — решает, нужно ли пересчитать анализ для
    комментария при следующей сборке снапшота;
  * ``update_subproblem_drafts`` — наращивает черновики подпроблем и
    кейсов в ``VkPainDraft`` по одному обработанному комментарию.

Функции мутируют переданные объекты и ничего не возвращают (кроме
``analysis_needs_refresh``). БД не трогаем — это делает caller.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from backend.app.config import settings
from backend.modules.analytics.constants import SUBCATEGORY_ALIASES
from backend.db.comment_analysis import CommentAnalysis
from backend.db.enums import RelevanceEnum, SentimentEnum
from backend.modules.analytics.dtos.drafts import (
    VkCaseDraft,
    VkPainDraft,
    VkSubproblemDraft,
)
from backend.modules.analytics.utils.case_extractor import (
    case_dedupe_key,
    case_display_title,
    case_location_key,
    is_valid_case_title,
)
from backend.modules.analytics.utils.category_classifier import (
    normalize_hierarchy_values,
)
from backend.modules.analytics.utils.comment_examples import (
    append_comment_example_to_list,
)
from backend.modules.analytics.utils.official_response import (
    is_meaningful_official_response,
    looks_like_official_response,
)
from backend.modules.analytics.utils.sentiment_rules import (
    fallback_relevance,
    looks_like_noise_non_pain,
)
from backend.modules.analytics.utils.signal_counts import bump_signal_counts
from backend.modules.analytics.utils.text_normalize import string_dict, trim_text
from backend.modules.llm.clients import get_default_llm_model

# Типы сообщений, которые считаем «жалобами» при подсчёте complaint_count.
MESSAGE_TYPES_FOR_COMPLAINT = {"complaint", "sarcasm"}


def apply_rule_based_analysis(
    analysis: CommentAnalysis,
    *,
    text: str,
    generated_at: datetime,
    rule_topics: set[str],
    rule_sentiment: SentimentEnum,
    rule_has_request: bool,
    author_name: str | None = None,
) -> None:
    """Заполняет ``analysis`` результатами keyword-разбора комментария.

    Если коммент похож на официальный ответ / модераторский ответ паблика
    (``looks_like_official_response``), помечаем его как нерелевантный и
    официальный — он не должен попадать в pains.
    """

    if looks_like_official_response(text, author_name):
        analysis.sentiment = SentimentEnum.neutral
        analysis.relevance = RelevanceEnum.irrelevant
        analysis.confidence = 0.85
        analysis.summary = trim_text(text)
        analysis.topics = sorted(rule_topics)
        analysis.model_version = "vk_rule_based_v2"
        analysis.analyzed_at = generated_at
        analysis.author_type = "official"
        analysis.message_type = "offtopic"
        analysis.classification_source = "fallback"
        analysis.is_official_response = True
        analysis.hierarchy = {"category": "", "subcategory": "", "case": ""}
        analysis.entities = {}
        return

    rule_relevance = fallback_relevance(rule_topics, rule_has_request, rule_sentiment)
    if rule_relevance == RelevanceEnum.relevant and looks_like_noise_non_pain(text):
        rule_relevance = RelevanceEnum.irrelevant
    message_type = "offtopic"
    if rule_has_request and rule_relevance == RelevanceEnum.relevant:
        message_type = "request"
    elif rule_sentiment == SentimentEnum.negative and rule_relevance == RelevanceEnum.relevant:
        # сарказм — тон, а не тип: негатив с предметом остаётся жалобой
        message_type = "complaint"
    elif rule_sentiment == SentimentEnum.positive and rule_relevance == RelevanceEnum.relevant:
        message_type = "gratitude"

    analysis.sentiment = rule_sentiment
    analysis.relevance = rule_relevance
    analysis.confidence = 0.4
    analysis.summary = trim_text(text)
    analysis.topics = sorted(rule_topics)
    analysis.model_version = "vk_rule_based_v2"
    analysis.analyzed_at = generated_at
    analysis.author_type = "citizen"
    analysis.message_type = message_type
    is_relevant = rule_relevance == RelevanceEnum.relevant
    # Категорию правилами НЕ проставляем: их точность по категории ~44% (мусор
    # вида «школа→Связь»). Релевантные уходят в needs_review — категорию даёт LLM.
    analysis.classification_source = "needs_review" if is_relevant else "fallback"
    analysis.is_official_response = False
    analysis.hierarchy = {"category": "", "subcategory": "", "case": ""}
    analysis.entities = {}


def apply_llm_analysis(
    analysis: CommentAnalysis,
    *,
    payload: Any,
    generated_at: datetime,
    source_text: str,
) -> None:
    """Заполняет ``analysis`` результатом LLM-разбора с нормализацией иерархии."""

    raw_hierarchy = payload.hierarchy.model_dump()
    normalized_category, normalized_subcategory, normalized_case = normalize_hierarchy_values(
        category=str(raw_hierarchy.get("category") or ""),
        subcategory=str(raw_hierarchy.get("subcategory") or ""),
        case_name=str(raw_hierarchy.get("case") or ""),
        source_text=source_text,
    )
    hierarchy = {
        "category": normalized_category,
        "subcategory": normalized_subcategory,
        "case": normalized_case,
    }
    topics = [
        item
        for item in (hierarchy.get("category"), hierarchy.get("subcategory"))
        if item
    ]
    # Модель иногда принимает одно VK-упоминание за шаблонный ответ
    # администрации. Без содержательного текста такой комментарий не может
    # быть ответом организации, независимо от её оценки.
    is_meaningful_response = is_meaningful_official_response(source_text)
    model_marks_official = payload.is_official_response or payload.author_type in {"admin", "official"}
    author_type = payload.author_type
    is_official_response = bool(payload.is_official_response)
    if model_marks_official and not is_meaningful_response:
        author_type = "citizen"
        is_official_response = False

    analysis.sentiment = SentimentEnum(payload.sentiment)
    analysis.relevance = (
        RelevanceEnum.irrelevant
        if is_official_response
        or author_type in {"admin", "official"}
        or payload.message_type == "offtopic"
        or payload.relevance == "irrelevant"
        else RelevanceEnum.relevant
    )
    # Уверенность берём у модели, а не константой: на ней строится needs_review
    # и доклассификация. Старый промпт мог её не вернуть — тогда сработает
    # дефолт схемы (0.5), и запись честно попадёт в ревью.
    confidence = float(getattr(payload, "confidence", 0.5) or 0.0)
    analysis.confidence = confidence
    analysis.candidates = [
        item.model_dump() if hasattr(item, "model_dump") else dict(item)
        for item in (getattr(payload, "candidates", None) or [])
    ]
    analysis.summary = payload.summary
    analysis.topics = topics
    analysis.model_version = get_default_llm_model()
    analysis.analyzed_at = generated_at
    analysis.author_type = author_type
    analysis.message_type = payload.message_type
    # classification_source:
    #   llm           — LLM назвала содержательную категорию;
    #   llm_other     — LLM сама вернула «Другое» (валидное решение модели);
    #   llm_needs_review — relevance=relevant, но нормализация категорию не вытащила;
    #   fallback      — irrelevant или служебный ответ.
    if normalized_category and normalized_category != "Другое":
        analysis.classification_source = "llm"
    elif normalized_category == "Другое":
        analysis.classification_source = "llm_other"
    elif payload.relevance == "relevant":
        analysis.classification_source = "llm_needs_review"
    else:
        analysis.classification_source = "fallback"
    analysis.is_official_response = is_official_response
    # Safety-net: у нерелевантных комментов категории/подпроблемы/кейса быть не
    # должно. Модель 7B вопреки промпту иногда вешает их на irrelevant — здесь
    # детерминированно очищаем, чтобы мусор не попадал в панели по «сырой»
    # category. Универсально, не зависит от послушности конкретной модели.
    if analysis.relevance == RelevanceEnum.irrelevant:
        analysis.hierarchy = {"category": "", "subcategory": "", "case": ""}
    else:
        analysis.hierarchy = hierarchy
    analysis.entities = payload.entities.model_dump()
    # На ручное ревью зовём только релевантные с категорией: у шума низкая
    # уверенность ничего не меняет, а ревью нужно там, где решение влияет на боли.
    analysis.needs_review = (
        analysis.relevance == RelevanceEnum.relevant
        and bool(normalized_category)
        and confidence < settings.LLM_LOW_CONFIDENCE_THRESHOLD
    )


def analysis_needs_refresh(analysis: CommentAnalysis | None) -> bool:
    """True, если у комментария нет полноценного анализа и нужен повторный разбор."""

    if analysis is None:
        return True
    if str(getattr(analysis, "classification_source", "") or "") == "llm_needs_review":
        return False
    if not str(getattr(analysis, "author_type", "") or "").strip():
        return True
    if not str(getattr(analysis, "message_type", "") or "").strip():
        return True
    if getattr(analysis, "relevance", None) is None:
        return True

    message_type = str(getattr(analysis, "message_type", "") or "").strip().lower()
    if message_type not in {"offtopic", "gratitude"}:
        hierarchy = string_dict(getattr(analysis, "hierarchy", None))
        if not hierarchy.get("category"):
            return True
    return False


def update_subproblem_drafts(
    bucket: VkPainDraft,
    *,
    subcategory: str,
    case_name: str,
    text: str,
    message_type: str,
    sentiment: SentimentEnum,
    publication_url: str | None,
    comment_external_id: str | None,
    comment_id: uuid.UUID,
    publication_id: uuid.UUID,
) -> None:
    """Добавляет один комментарий в подпроблему и (если есть) в кейс боли."""

    if not subcategory:
        return

    # Чип подпроблемы — только из таксономии своей категории: чужая или
    # свободная подкатегория в старых данных не должна попадать в выдачу.
    allowed = SUBCATEGORY_ALIASES.get(bucket.title)
    if allowed is not None and subcategory not in allowed:
        return

    subproblem = bucket.subproblem_items.setdefault(
        subcategory,
        VkSubproblemDraft(title=subcategory),
    )
    subproblem.comment_ids.add(comment_id)
    subproblem.publication_ids.add(publication_id)
    if publication_url:
        subproblem.source_urls.add(publication_url)
    append_comment_example_to_list(
        subproblem.comment_examples,
        text=text,
        message_type=message_type,
        sentiment=sentiment,
        publication_url=publication_url,
        comment_external_id=comment_external_id,
        comment_id=comment_id,
    )
    bump_signal_counts(
        subproblem.sentiment_counts,
        subproblem.message_type_counts,
        sentiment=sentiment,
        message_type=message_type,
    )
    if message_type == "request":
        subproblem.request_count += 1
    if message_type in MESSAGE_TYPES_FOR_COMPLAINT:
        subproblem.complaint_count += 1

    # Не создаём кейс из мусора: пустой case, название категории/подкатегории
    # («Торговля и регулирование»), плейсхолдеры («ул. Не указана»). Тот же
    # фильтр, что в UI/отчёте — но в источнике, чтобы мусор не сохранялся вовсе.
    if not case_name or not is_valid_case_title(case_name):
        return

    # Дедуп кейса: если в case_name выделяется конкретная локация — ключуем по
    # нормализованной локации, чтобы «с. Успенка, Рыбинский район» и «село
    # Успенка, Рыбинский район, Красноярский край» были ОДНИМ кейсом. Только
    # если локация не выделилась — падаем на текстовый семантический ключ.
    location = case_location_key(case_name)
    case_key = f"loc:{location}" if location else case_dedupe_key(case_name, text)
    case_item = subproblem.cases.setdefault(
        case_key,
        VkCaseDraft(title=case_display_title(case_name, text)),
    )
    case_item.comment_ids.add(comment_id)
    case_item.publication_ids.add(publication_id)
    if publication_url:
        case_item.source_urls.add(publication_url)
    append_comment_example_to_list(
        case_item.comment_examples,
        text=text,
        message_type=message_type,
        sentiment=sentiment,
        publication_url=publication_url,
        comment_external_id=comment_external_id,
        comment_id=comment_id,
    )
    bump_signal_counts(
        case_item.sentiment_counts,
        case_item.message_type_counts,
        sentiment=sentiment,
        message_type=message_type,
    )
    if message_type == "request":
        case_item.request_count += 1
    if message_type in MESSAGE_TYPES_FOR_COMPLAINT:
        case_item.complaint_count += 1
