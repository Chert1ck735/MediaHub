"""Правила оценки серьёзности боли (severity) и нормализации приоритета."""
from __future__ import annotations


_SEVERITY_RANK = {"low": 0, "medium": 1, "high": 2, "critical": 3}
_ESCALATE = {"low": "medium", "medium": "high", "high": "critical", "critical": "critical"}


def severity_from_mentions(mentions_count: int) -> str:
    """Возвращает уровень серьёзности по числу упоминаний боли."""

    if mentions_count >= 50:
        return "critical"
    if mentions_count >= 20:
        return "high"
    if mentions_count >= 8:
        return "medium"
    return "low"


def severity_from_share(mentions: int, total: int, *, negative_ratio: float | None = None) -> str:
    """Каноническая severity: по доле в срезе, с потолком по абсолютным упоминаниям.

    Единый источник для билда, списка и детали. Потолок нужен, чтобы на мелком
    паблике пара упоминаний с высокой долей не давала critical. ``negative_ratio``
    (если передан) эскалирует уровень на сильно негативных болях.
    """

    if total <= 0 or mentions <= 0:
        return "low"
    share = mentions / total
    if share >= 0.25:
        base = "critical"
    elif share >= 0.12:
        base = "high"
    elif share >= 0.05:
        base = "medium"
    else:
        base = "low"
    if negative_ratio is not None and mentions >= 5 and negative_ratio >= 0.70:
        base = _ESCALATE[base]
    return min(base, severity_from_mentions(mentions), key=_SEVERITY_RANK.get)


def normalize_priority(value: str | None) -> str | None:
    """Приводит произвольное значение к каноническому ``low/medium/high/critical``."""

    if not value:
        return None
    low = value.strip().lower()
    if low in {"low", "medium", "high", "critical"}:
        return low
    return None
