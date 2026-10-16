"""Rule-based классификация комментариев: тональность, темы, тип сообщения.

Эти функции построены на словарях из `analytics.constants`
(`NEGATIVE_KEYWORDS`, `POSITIVE_KEYWORDS`, `TOPIC_KEYWORDS`,
`REQUEST_KEYWORDS`, `VK_THEME_META`) и используются как первичный фильтр
до обращения к LLM. Все функции чистые — не ходят в БД и не вызывают
внешних сервисов.
"""
from __future__ import annotations

from backend.db.enums import RelevanceEnum, SentimentEnum
from backend.modules.analytics.constants import (
    NEGATIVE_KEYWORDS,
    POSITIVE_KEYWORDS,
    REQUEST_KEYWORDS,
    TOPIC_KEYWORDS,
    VK_THEME_META,
)


def topics_for_text(value: str) -> set[str]:
    """Возвращает множество тем, ключевые слова которых встречаются в тексте."""

    low = value.lower()
    topics: set[str] = set()
    for topic, keywords in TOPIC_KEYWORDS.items():
        if any(keyword in low for keyword in keywords):
            topics.add(topic)
    return topics


def sentiment_for_text(value: str) -> SentimentEnum:
    """Определяет тональность по балансу позитивных и негативных триггеров."""

    low = value.lower()
    negative_hits = sum(1 for keyword in NEGATIVE_KEYWORDS if keyword in low)
    positive_hits = sum(1 for keyword in POSITIVE_KEYWORDS if keyword in low)
    if negative_hits > positive_hits:
        return SentimentEnum.negative
    if positive_hits > negative_hits:
        return SentimentEnum.positive
    return SentimentEnum.neutral


def has_request_signal(value: str) -> bool:
    """Проверяет, содержит ли текст словесные маркеры запроса/просьбы."""

    low = value.lower()
    return any(keyword in low for keyword in REQUEST_KEYWORDS)


def looks_sarcastic(value: str) -> bool:
    """Грубая эвристика сарказма: одновременно позитивная и негативная лексика."""

    low = value.lower()
    positive_hits = any(keyword in low for keyword in POSITIVE_KEYWORDS)
    negative_hits = any(keyword in low for keyword in NEGATIVE_KEYWORDS)
    quoted_positive = any(
        token in value
        for token in ('"чист', "'чист", '"отлич', "'отлич", '"спасибо"', "'спасибо'")
    )
    return (positive_hits and negative_hits) or quoted_positive


_GRATITUDE_MARKERS = (
    "поздравля", "соболезну", "благодар", "замечательн", "восхитительн",
    "молодц", "умниц", "хороший фестиваль", "приятный человек", "успеха всем",
)
_SPAM_MARKERS = ("сбор на пересадку", "костного мозга", "карта сбербанк", "помогите собрать", "реквизиты для")
_EVENT_MARKERS = ("мероприят", "фестивал", "оргкомитет", "конкурс", "день туризма", "акци", "эфир")
_SERVICE_TOPICS = frozenset({"housing", "roads", "ecology", "social", "safety", "telecom", "economy"})


def looks_like_noise_non_pain(text: str) -> bool:
    """Шум, который не боль: благодарности/соболезнования, спам-сборы, вопросы про мероприятия без предметной темы."""

    low = text.lower()
    if any(s in low for s in _SPAM_MARKERS):
        return True
    if any(g in low for g in _GRATITUDE_MARKERS) and not has_request_signal(text):
        return True
    if any(e in low for e in _EVENT_MARKERS) and not (topics_for_text(text) & _SERVICE_TOPICS):
        return True
    return False


def topics_for_pain(title: str, category: str | None) -> set[str]:
    """Объединяет темы из названия боли и её категории."""

    topics = topics_for_text(title)
    if category:
        topics.update(topics_for_text(category))
    return topics


def select_related_items(
    items: list[str],
    pain_topics: set[str],
    *,
    include_governance_for_all: bool = False,
) -> list[str]:
    """Отбирает элементы, у которых пересекаются темы с темами боли.

    Если `include_governance_for_all=True`, дополнительно пропускает
    элементы темы `governance` (актуально для общих рекомендаций по
    работе с обращениями).
    """

    related: list[str] = []
    for item in items:
        item_topics = topics_for_text(item)
        if pain_topics & item_topics:
            related.append(item)
            continue
        if include_governance_for_all and "governance" in item_topics:
            related.append(item)
    return related


# governance — последним: предметная тема важнее «обратной связи».
_TOPIC_PRIORITY = ("safety", "social", "housing", "roads", "ecology", "telecom", "economy", "governance")


def rule_category_from_topics(rule_topics: set[str]) -> str:
    """Маппит тему на категорию; предметные темы приоритетнее governance."""

    for topic in _TOPIC_PRIORITY:
        if topic in rule_topics:
            meta = VK_THEME_META.get(topic)
            if meta is not None:
                return meta["category"]
    for topic in sorted(rule_topics):
        meta = VK_THEME_META.get(topic)
        if meta is not None:
            return meta["category"]
    return ""


def fallback_relevance(
    rule_topics: set[str],
    has_request: bool,
    sentiment: SentimentEnum | None = None,
) -> RelevanceEnum:
    """Relevant только при явном признаке проблемы: запрос или тема с негативом."""

    if has_request:
        return RelevanceEnum.relevant
    if rule_topics and sentiment == SentimentEnum.negative:
        return RelevanceEnum.relevant
    return RelevanceEnum.irrelevant
