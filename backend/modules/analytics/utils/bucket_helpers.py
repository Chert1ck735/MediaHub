"""Хелперы для сборки «бакетов» аналитики (theme/title/meta).

Бакет — это группа болей по теме (housing / roads / ecology / ...).
Эти функции отвечают за маппинг свободных строк категория/подкатегория
в каноническую тему и за подготовку человекочитаемых заголовков.
"""
from __future__ import annotations

from backend.modules.analytics.constants import VK_THEME_META
from backend.modules.analytics.dtos.drafts import VkPainDraft
from backend.modules.analytics.utils.severity_rules import severity_from_share
from backend.modules.analytics.utils.text_normalize import normalized_lookup_text


def bucket_title(
    category: str,
    subcategory: str | None,
    case_name: str | None = None,
) -> str:
    """Собирает человекочитаемый заголовок бакета."""

    category = category.strip()
    subcategory = (subcategory or "").strip()
    case_name = (case_name or "").strip()
    if subcategory and subcategory.lower() != category.lower():
        return f"{category}: {subcategory}"
    if subcategory:
        return subcategory
    if category:
        return category
    return case_name or "Other"


_CATEGORY_THEME_MAP: dict[str, str] = {
    "жкх": "housing",
    "жкх и городская среда": "housing",
    "дороги и транспорт": "roads",
    "экология": "ecology",
    "экология и санитарное состояние": "ecology",
    "социальная инфраструктура": "social",
    "социальная сфера": "social",
    "управление и коммуникации": "governance",
    "управление и обратная связь": "governance",
    "безопасность и чс": "safety",
    "экономика, торговля и регулирование": "economy",
}

_THEME_KEYWORDS: dict[str, tuple[str, ...]] = {
    "housing": ("жкх", "коммун", "отоп", "вода", "подъезд", "двор", "капремонт", "управля", "благоуст", "парк", "сквер"),
    "roads": ("дорог", "ям", "асфальт", "тротуар", "останов", "транспорт", "автобус", "парков", "ливнев", "весов", "большегруз"),
    "social": ("школ", "сад", "врач", "поликлиник", "больниц", "социал", "образован", "мед", "инвалид", "льгот", "выплат"),
    "ecology": ("эколог", "свалк", "мусор", "дым", "запах", "воздух", "санитар", "уборк", "гряз"),
    "governance": ("администра", "власть", "обращен", "ответ", "информ", "срок", "чинов", "ведом", "отписк"),
    "safety": ("чс", "авар", "обвал", "погиб", "смерт", "угроз", "происшеств", "дтп", "аварийн"),
    "economy": ("магазин", "алкогол", "продаж", "торгов", "лиценз", "контроль"),
}


def bucket_theme_key(category: str | None, subcategory: str | None = None) -> str | None:
    """Маппит категорию/подкатегорию в каноническую тему (housing/roads/...)."""

    category_key = normalized_lookup_text(category or "")
    if category_key in _CATEGORY_THEME_MAP:
        return _CATEGORY_THEME_MAP[category_key]

    low = f"{category or ''} {subcategory or ''}".lower()
    for theme, keywords in _THEME_KEYWORDS.items():
        if any(keyword in low for keyword in keywords):
            return theme
    return None


def bucket_meta(category: str | None, subcategory: str | None = None) -> dict[str, str]:
    """Возвращает метаданные бакета: title, category, risk, quick_win, strategic."""

    theme_key = bucket_theme_key(category, subcategory)
    if theme_key and theme_key in VK_THEME_META:
        return VK_THEME_META[theme_key]
    title = bucket_title(category or "Прочее", subcategory)
    category_title = (category or "Прочее").strip() or "Прочее"
    return {
        "title": title,
        "category": category_title,
        "risk": f"Рост повторяющихся обращений по теме «{title}».",
        "quick_win": f"Собрать адресные кейсы по теме «{title}», проверить статусы и дать публичный ответ по ближайшим действиям.",
        "strategic": f"Сформировать системный план решений по теме «{title}» с ответственными и контрольными сроками.",
    }


def entity_suffix(entities: dict[str, str]) -> str:
    """Формирует короткий человекочитаемый суффикс с адресом/учреждением/сроком."""

    labels = {
        "address": "адрес",
        "institution": "учреждение",
        "reference_number": "номер",
        "deadline": "срок",
    }
    parts: list[str] = []
    for key in ("address", "institution", "reference_number", "deadline"):
        value = entities.get(key)
        if value:
            parts.append(f"{labels[key]}: {value}")
    if not parts:
        return ""
    return f" ({'; '.join(parts[:2])})"


def severity_from_bucket(bucket: VkPainDraft, total_mentions: int = 0) -> str:
    """Уровень серьёзности боли — относительно общего объёма упоминаний snapshot'a.

    Старая логика (абсолютный score >= 50 → critical) выдавала «всё
    красное» на любой нормальной выгрузке. Текущая считает долю боли
    в общем потоке и опционально эскалирует на сильно негативный
    sentiment.
    """

    mentions = len(bucket.comment_ids)
    if total_mentions <= 0:
        # Legacy absolute scoring — для обратной совместимости.
        score = mentions + min(len(bucket.requests), 3) + min(len(bucket.negative_points), 3)
        if len(bucket.publication_ids) >= 2:
            score += 1
        if len(bucket.public_ids) >= 2:
            score += 1
        if score >= 50:
            return "critical"
        if score >= 25:
            return "high"
        if score >= 10:
            return "medium"
        return "low"

    negative = int(bucket.sentiment_counts.get("negative", 0))
    return severity_from_share(mentions, total_mentions, negative_ratio=negative / max(mentions, 1))


def compose_communication_strategy(meta: dict[str, str], title: str) -> str:
    """Соединяет quick_win и strategic в короткое описание стратегии коммуникации."""

    quick = meta.get("quick_win", "").strip()
    strategic = meta.get("strategic", "").strip()
    if quick and strategic:
        return f"{quick} {strategic}"
    if strategic:
        return strategic
    if quick:
        return quick
    return f"Сформировать публичный план решений по теме «{title}»."
