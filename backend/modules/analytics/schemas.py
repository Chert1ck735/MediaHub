from datetime import datetime
from typing import Literal, Any

from pydantic import BaseModel, Field

class LegacyGlobalProblemItem(BaseModel):
    """Пункт legacy-payload с глобальной проблемой."""

    problem: str
    frequency_estimate: int = 0
    evidence_posts: list[str] = Field(default_factory=list)


class LegacyPossibleSolution(BaseModel):
    """Legacy-решение для глобальной проблемы."""

    problem: str
    solutions: list[str] = Field(default_factory=list)
    priority: str | None = None


class LegacyGlobalProblemPayload(BaseModel):
    """Legacy-payload аналитики до перехода на structured pains."""

    global_summary: str | None = None
    top_global_problems: list[LegacyGlobalProblemItem] = Field(default_factory=list)
    citizens_requests: list[str] = Field(default_factory=list)
    dissatisfaction_points: list[str] = Field(default_factory=list)
    satisfaction_points: list[str] = Field(default_factory=list)
    possible_solutions: list[LegacyPossibleSolution] = Field(default_factory=list)
    risk_zones: list[str] = Field(default_factory=list)
    quick_wins_30_days: list[str] = Field(default_factory=list)
    strategic_actions_3_6_months: list[str] = Field(default_factory=list)


class StructuredPainStrategy(BaseModel):
    """Стратегия действий по боли."""

    priority: str | None = None
    actions: list[str] = Field(default_factory=list)


class PainCommentExample(BaseModel):
    """Короткий пример комментария, связанного с болью."""

    text: str
    url: str | None = None
    publication_url: str | None = None
    comment_id: str | None = None
    message_type: str | None = None
    sentiment: str | None = None


class SentimentBreakdown(BaseModel):
    """Распределение комментариев по тональности."""

    positive: int = 0
    neutral: int = 0
    negative: int = 0


class MessageTypeBreakdown(BaseModel):
    """Распределение комментариев по типам сообщения."""

    complaint: int = 0
    request: int = 0
    gratitude: int = 0
    offtopic: int = 0
    sarcasm: int = 0


class RelevanceBreakdown(BaseModel):
    """Распределение комментариев по релевантности."""

    relevant: int = 0
    irrelevant: int = 0


class CategoryCountItem(BaseModel):
    """Агрегат по категории боли."""

    category: str
    count: int = 0
    negative_count: int = 0
    neutral_count: int = 0
    positive_count: int = 0


class StructuredCaseItem(BaseModel):
    """Адресный кейс внутри подпроблемы."""

    title: str
    raw_title: str | None = None
    mentions_count: int = 0
    comment_examples: list[PainCommentExample] = Field(default_factory=list)
    sentiment_counts: SentimentBreakdown = Field(default_factory=SentimentBreakdown)
    message_type_counts: MessageTypeBreakdown = Field(default_factory=MessageTypeBreakdown)
    request_count: int = 0
    complaint_count: int = 0
    source_urls: list[str] = Field(default_factory=list)


class StructuredSubproblemItem(BaseModel):
    """Подпроблема внутри боли."""

    title: str
    description: str | None = None
    mentions_count: int = 0
    comment_examples: list[PainCommentExample] = Field(default_factory=list)
    sentiment_counts: SentimentBreakdown = Field(default_factory=SentimentBreakdown)
    message_type_counts: MessageTypeBreakdown = Field(default_factory=MessageTypeBreakdown)
    request_count: int = 0
    complaint_count: int = 0
    source_urls: list[str] = Field(default_factory=list)
    cases: list[StructuredCaseItem] = Field(default_factory=list)


class StructuredPainItem(BaseModel):
    """Структурированная боль внутри snapshot payload."""

    title: str
    description: str | None = None
    category: str | None = None
    subcategory: str | None = None
    mentions_count: int = 0
    publications_count: int = 0
    severity_level: Literal["low", "medium", "high", "critical"] = "medium"
    status: Literal["active", "in_progress", "resolved"] = "active"
    citizens_requests: list[str] = Field(default_factory=list)
    dissatisfaction_points: list[str] = Field(default_factory=list)
    positive_signals: list[str] = Field(default_factory=list)
    sentiment_counts: SentimentBreakdown = Field(default_factory=SentimentBreakdown)
    message_type_counts: MessageTypeBreakdown = Field(default_factory=MessageTypeBreakdown)
    request_count: int = 0
    complaint_count: int = 0
    comment_examples: list[PainCommentExample] = Field(default_factory=list)
    complaint_examples: list[str] = Field(default_factory=list)
    request_examples: list[str] = Field(default_factory=list)
    positive_examples: list[str] = Field(default_factory=list)
    subproblems: list[str] = Field(default_factory=list)
    subproblem_items: list[StructuredSubproblemItem] = Field(default_factory=list)
    communication_strategy: str | None = None
    evidence_posts: list[str] = Field(default_factory=list)
    strategy: StructuredPainStrategy | None = None


class StructuredPainAnalyticsPayload(BaseModel):
    """Канонический payload snapshot'а аналитики."""

    export_version: str = "1.0"
    source_format: str = "pain_analytics_v1"
    source_name: str = "manual_import"
    generated_at: datetime | None = None
    global_summary: str | None = None
    citizens_requests: list[str] = Field(default_factory=list)
    dissatisfaction_points: list[str] = Field(default_factory=list)
    satisfaction_points: list[str] = Field(default_factory=list)
    risk_zones: list[str] = Field(default_factory=list)
    quick_wins_30_days: list[str] = Field(default_factory=list)
    strategic_actions_3_6_months: list[str] = Field(default_factory=list)
    pains: list[StructuredPainItem] = Field(default_factory=list)


class AnalyticsNormalizeRequest(BaseModel):
    """Запрос нормализации внешнего payload."""

    source_name: str = "manual_import"
    payload: dict[str, Any]


class AnalyticsNormalizeResponse(BaseModel):
    """Ответ нормализации внешнего payload."""

    normalized: StructuredPainAnalyticsPayload


class AnalyticsImportResponse(BaseModel):
    """Ответ импорта snapshot'а."""

    snapshot_id: str
    source_name: str
    source_format: str
    pains_imported: int
    generated_at: str


class SlaStats(BaseModel):
    """SLA ответа организации: на сообщения аудитории отвечают/за сколько."""

    appeals: int = 0                    # обращения в скоупе — то же число, что в /summary
    answered: int = 0
    response_rate: float = 0.0          # % обращений с официальным ответом
    median_hours: float | None = None
    avg_hours: float | None = None
    within_sla_rate: float = 0.0        # % ответов в срок (из отвеченных)
    sla_hours: float = 48.0
    official_total: int = 0             # всего официальных ответов организаций в скоупе


class Incident(BaseModel):
    """Инцидент реестра (лайт): адресный кейс как отслеживаемая задача."""

    problem: str
    category: str
    agency: str
    mentions: int
    answered: int
    age_hours: int
    status: str   # new | in_work | overdue


class AgencyStat(BaseModel):
    """Строка рейтинга организаций по реакции на обращения."""

    agency: str
    incidents: int
    mentions: int
    answered: int
    overdue: int
    new: int
    response_rate: float


class Alert(BaseModel):
    """Всплеск обращений по категории (последнее окно против предыдущего)."""

    category: str
    recent: int
    prior: int
    growth_pct: int | None = None   # None — рост с нуля
    window_days: int = 7


class PainMapPoint(BaseModel):
    """Точка на карте болей: адресный кейс с координатами и весом."""

    name: str
    lat: float
    lon: float
    region: str = ""
    municipality: str = ""
    locality: str = ""
    district: str = ""
    count: int
    cases: list[str] = Field(default_factory=list)


class AddressCaseDeleteRequest(BaseModel):
    cases: list[str] = Field(..., min_length=1)


class AddressCaseDeleteResponse(BaseModel):
    cases: list[str] = Field(default_factory=list)
    updated_analyses: int = 0


class GeoCacheProviderStatus(BaseModel):
    """Настройка провайдера геокодинга без раскрытия секретов."""

    yandex_configured: bool
    dadata_configured: bool
    priority: list[str] = Field(default_factory=list)


class GeoCacheStatus(BaseModel):
    """Диагностика файлового кэша геокодинга."""

    path: str
    absolute_path: str
    exists: bool
    parent_exists: bool
    readable: bool
    writable: bool
    parent_writable: bool
    size_bytes: int | None = None
    modified_at: str | None = None
    total_entries: int = 0
    hit_entries: int = 0
    miss_entries: int = 0
    stale_miss_entries: int = 0
    malformed_entries: int = 0
    source_breakdown: dict[str, int] = Field(default_factory=dict)
    sample_keys: list[str] = Field(default_factory=list)
    read_error: str | None = None
    max_new_per_request: int
    miss_ttl_seconds: int
    timeout_seconds: int
    providers: GeoCacheProviderStatus


class AddressCaseGeocodingStats(BaseModel):
    """Покрытие geo-кэшем адресных кейсов, пригодных для карты."""

    total_cases: int = 0
    geocoded_cases: int = 0
    not_geocoded_cases: int = 0
    rejected_cases: int = 0
    untried_cases: int = 0
    # Внутри rejected_cases: провайдер не ответил вовсе — кончилась норма ключей
    # или сорвалась сеть. Такие стоит переспросить, честные отказы — нет.
    unasked_cases: int = 0
    skipped_invalid_cases: int = 0
    total_mentions: int = 0
    geocoded_mentions: int = 0
    not_geocoded_mentions: int = 0
    rejected_mentions: int = 0
    untried_mentions: int = 0
    cache_hit_entries: int = 0
    cache_miss_entries: int = 0
    cache_total_entries: int = 0
    cache_read_error: str | None = None
    cache_modified_at: str | None = None


class AddressCaseGeocodingBackfillResponse(BaseModel):
    """Один проход ручного догеокодирования адресных кейсов."""

    considered: int = 0
    already_cached: int = 0
    requests_made: int = 0
    geocoded: int = 0
    missed: int = 0
    fresh_miss_skipped: int = 0
    invalid_skipped: int = 0
    budget_exhausted: int = 0
    remaining: int = 0


class GeoKeysRequest(BaseModel):
    """Список ключей Яндекс-геокодера. Пул перебирает их по порядку."""

    keys: list[str] = Field(default_factory=list, max_length=20)


class GeoCacheRotateResponse(BaseModel):
    """Результат ротации файлового кэша геокодинга."""

    rotated: bool
    previous_path: str
    backup_path: str | None = None
    message: str
    status_after: GeoCacheStatus


class CaseCommentsRequest(BaseModel):
    """Запрос комментариев адресных кейсов точки карты."""

    cases: list[str]
    period: str = "week"
    public_social_link_id: str | None = None
    problem_type: str | None = None
    municipality_name: str | None = None


class CaseComment(BaseModel):
    """Коммент, относящийся к адресному кейсу (drill-down на карте)."""

    text: str
    date: str | None = None
    url: str | None = None
    comment_url: str | None = None
    sentiment: str = ""
    public: str | None = None
    category: str = ""
    subcategory: str = ""
    has_official_response: bool = False
    official_response_url: str | None = None
    official_response_text: str | None = None
    official_response_date: str | None = None


class AnalyticsSummaryResponse(BaseModel):
    """Сводка analytics dashboard."""

    snapshot_id: str
    generated_at: str
    global_summary: str | None
    source_label: str
    platforms: list[str] = Field(default_factory=list)
    pain_count: int
    total_comment_count: int = 0
    classified_comment_count: int = 0
    relevant_comment_count: int
    complaint_count: int
    request_count: int
    # обращения = жалобы + просьбы; та же база, что у SLA и «Топ категорий»
    appeal_count: int = 0
    gratitude_count: int
    other_count: int = 0
    filtered_count: int
    unclassified_count: int = 0
    recommended_post_window: str | None = None
    top_pains: list[str] = Field(default_factory=list)
    sentiment_breakdown: SentimentBreakdown = Field(default_factory=SentimentBreakdown)
    message_type_breakdown: MessageTypeBreakdown = Field(default_factory=MessageTypeBreakdown)
    relevance_breakdown: RelevanceBreakdown = Field(default_factory=RelevanceBreakdown)
    category_breakdown: list[CategoryCountItem] = Field(default_factory=list)
    sla: SlaStats = Field(default_factory=SlaStats)


class PainCaseRef(BaseModel):
    """Краткая ссылка на адресный кейс боли."""

    title: str
    raw_title: str | None = None
    mentions_count: int = 0


class PainSubproblemRef(BaseModel):
    """Подпроблема боли с числом упоминаний — для отчёта главе."""

    title: str
    mentions_count: int = 0


class PainListItemResponse(BaseModel):
    """Элемент списка болей."""

    id: str
    title: str
    category: str | None
    subcategory: str | None = None
    mentions_count: int
    publications_count: int = 0
    severity_level: str
    status: str
    comment_examples: list[PainCommentExample] = Field(default_factory=list)
    subproblems: list[str] = Field(default_factory=list)
    subproblem_items: list[PainSubproblemRef] = Field(default_factory=list)
    subproblem_count: int = 0
    top_cases: list[PainCaseRef] = Field(default_factory=list)
    cases_count: int = 0
    strategy_id: str | None = None
    communication_strategy: str | None = None
    strategy_preview: str | None = None
    evidence_posts: list[str] = Field(default_factory=list)


class ReactionGapEventItem(BaseModel):
    """Один замер reaction gap по посту."""

    post_id: str
    post_title: str | None = None
    anchor_at: str
    window_days: int
    before_count: int
    after_count: int
    gap_pct: float | None = None


class ReactionGapSummary(BaseModel):
    """Сводка reaction gap по боли."""

    avg_gap_pct: float | None = None
    measured_events: int = 0
    events: list[ReactionGapEventItem] = Field(default_factory=list)


class PainDetailResponse(BaseModel):
    """Детальная карточка боли."""

    id: str
    title: str
    description: str | None
    category: str | None
    subcategory: str | None = None
    mentions_count: int
    publications_count: int = 0
    severity_level: str
    status: str
    comment_examples: list[PainCommentExample] = Field(default_factory=list)
    subproblems: list[str] = Field(default_factory=list)
    subproblem_items: list[StructuredSubproblemItem] = Field(default_factory=list)
    top_cases: list[PainCaseRef] = Field(default_factory=list)
    cases_count: int = 0
    sentiment_counts: SentimentBreakdown = Field(default_factory=SentimentBreakdown)
    message_type_counts: MessageTypeBreakdown = Field(default_factory=MessageTypeBreakdown)
    request_count: int = 0
    complaint_count: int = 0
    communication_strategy: str | None = None
    strategy_ids: list[str] = Field(default_factory=list)
    strategies: list[str] = Field(default_factory=list)
    evidence_posts: list[str] = Field(default_factory=list)
    reaction_gap: ReactionGapSummary | None = None


class AnalyticsRebuildResponse(BaseModel):
    """Ответ фоновой пересборки VK snapshot."""

    snapshot_id: str
    generated_at: str
    pain_count: int
    reclassified_comments: int = 0
    llm_classified_comments: int = 0
    fallback_classified_comments: int = 0
    elapsed_seconds: float = 0.0
    comments_per_min: int = 0
    prefilter_used: bool = False
    prefilter_dropped: int = 0


class DeleteImportedPublicResponse(BaseModel):
    """Ответ удаления импортированной площадки."""

    public_id: str
    deleted_links: int
    deleted_publications: int
    deleted_comments: int
    deleted_posts: int
    snapshot_rebuilt: bool


class RegionOption(BaseModel):
    """Регион для выбора территории паблика."""

    id: str
    name: str
    code: str | None = None


class PublicRegionUpdateRequest(BaseModel):
    """Обновление региональной привязки паблика."""

    region_id: str | None = None
    municipality_name: str | None = None


class PublicRegionResponse(BaseModel):
    """Текущая региональная привязка паблика."""

    public_id: str
    region_id: str | None = None
    region_name: str | None = None
    municipality_name: str | None = None


class PublicLocationInferenceResponse(BaseModel):
    """Результат автоподбора региона/муниципалитета для площадок."""

    considered: int = 0
    updated_publics: int = 0
    updated_region: int = 0
    updated_municipality: int = 0
    unchanged: int = 0


class ClassifyBatchResponse(BaseModel):
    """Статистика одного батча классификации."""

    picked: int = 0
    succeeded: int = 0
    failed: int = 0
    skipped: int = 0
    avg_ms: float | None = None


class ClassificationReviewTaxonomy(BaseModel):
    """Категории и подкатегории для ручной доводки LLM-классификации."""

    categories: list[str] = Field(default_factory=list)
    subcategories: dict[str, list[str]] = Field(default_factory=dict)


class ClassificationReviewItem(BaseModel):
    """Комментарий, которому LLM не смогла назначить категорию."""

    analysis_id: str
    comment_id: str
    text: str
    summary: str | None = None
    sentiment: str | None = None
    message_type: str | None = None
    hierarchy: dict[str, Any] = Field(default_factory=dict)
    public_name: str | None = None
    publication_url: str | None = None
    comment_date: str | None = None


class ClassificationReviewPage(BaseModel):
    """Страница комментариев на ручную проверку категории."""

    items: list[ClassificationReviewItem] = Field(default_factory=list)
    total: int
    offset: int
    limit: int
    has_more: bool


class ClassificationReviewResolveRequest(BaseModel):
    """Ручное назначение категории для комментария."""

    category: str
    subcategory: str = ""
    case: str = ""


class ReclassifyRequest(BaseModel):
    """Запрос возврата комментариев в очередь классификации."""

    scope: str = Field(
        default="review",
        description=(
            "Какие комментарии вернуть в очередь. "
            "'review' — rule-based needs_review/unknown; "
            "'failed' — только failed; "
            "'unclassified' — всё без полноценной классификации; "
            "'all' — все relevant в организации."
        ),
    )


class ReclassifyResponse(BaseModel):
    """Ответ возврата комментариев в очередь классификации."""

    requeued: int


class RebuildNeededResponse(BaseModel):
    """Ответ проверки необходимости пересборки VK-аналитики."""

    needs_rebuild: bool
    reason: str
    new_comments: int = 0
    pending_classification: int = 0


class PublicationPainBucket(BaseModel):
    """Сколько комментариев публикации относится к конкретной боли."""

    pain_id: str
    pain_title: str
    pain_category: str | None = None
    comments_count: int


class PainTrendItem(BaseModel):
    """Тренд упоминаний боли по бакетам, размер которых зависит от периода."""

    pain_id: str
    counts: list[int] = Field(default_factory=list)
    bucket_days: int = 7


class PainEventPostRef(BaseModel):
    """Пост, связанный с событием боли."""

    post_id: str
    title: str
    scheduled_at: str | None = None
    status: str


class PainEventLink(BaseModel):
    """Событие, связанное с болью."""

    event_id: str
    title: str
    event_date: str
    location: str | None = None
    description: str | None = None
    relation_type: str = "addresses"
    posts: list[PainEventPostRef] = Field(default_factory=list)


class StrategyRegenerateResponse(BaseModel):
    """Ответ генерации новой стратегии по боли."""

    pain_id: str
    strategy_id: str
    description: str


class PainCommentItem(BaseModel):
    """Комментарий, связанный с болью."""

    comment_id: str
    text: str
    url: str | None = None
    publication_url: str | None = None
    sentiment: str | None = None
    message_type: str | None = None
    is_official_response: bool = False
    comment_date: str | None = None
    has_official_response: bool = False
    official_response_url: str | None = None
    official_response_text: str | None = None
    official_response_date: str | None = None


class PainCommentsPage(BaseModel):
    """Страница комментариев боли."""

    items: list[PainCommentItem] = Field(default_factory=list)
    total: int
    offset: int
    limit: int
    has_more: bool
