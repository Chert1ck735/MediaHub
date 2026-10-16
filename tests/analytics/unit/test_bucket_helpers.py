"""Характеристик-тесты: bucket_helpers (заголовки, темы, severity бакета)."""
from __future__ import annotations

import uuid

from backend.modules.analytics.dtos.drafts import VkPainDraft
from backend.modules.analytics.utils.bucket_helpers import (
    bucket_meta,
    bucket_theme_key,
    bucket_title,
    compose_communication_strategy,
    entity_suffix,
    severity_from_bucket,
)


def _draft(*, mentions: int = 0, negative: int = 0) -> VkPainDraft:
    d = VkPainDraft(topic="roads", title="Дороги", category="Дороги и транспорт")
    d.comment_ids = {uuid.uuid4() for _ in range(mentions)}
    d.sentiment_counts = {"positive": 0, "neutral": 0, "negative": negative}
    return d


def test_bucket_title():
    assert bucket_title("Дороги и транспорт", "качество дорог") == "Дороги и транспорт: качество дорог"
    # subcategory == category → возвращаем подкатегорию как есть
    assert bucket_title("Дороги", "Дороги") == "Дороги"
    # всё пусто → дефолт
    assert bucket_title("", "", "") == "Other"


def test_bucket_theme_key():
    assert bucket_theme_key("ЖКХ и городская среда") == "housing"
    assert bucket_theme_key("дороги и транспорт") == "roads"
    # по ключевому слову, когда категория не каноничная
    assert bucket_theme_key(None, "дорога разбита") == "roads"
    assert bucket_theme_key("совсем непонятная тема") is None


def test_bucket_meta_canonical_and_fallback():
    meta = bucket_meta("ЖКХ и городская среда")
    assert meta["category"] == "ЖКХ и городская среда"
    assert "risk" in meta and "quick_win" in meta and "strategic" in meta

    fallback = bucket_meta("Прочее непонятное")
    assert fallback["category"] == "Прочее непонятное"
    assert "risk" in fallback


def test_entity_suffix():
    suffix = entity_suffix({"address": "ул. Ленина 5", "institution": "Школа 1"})
    assert suffix.startswith(" (адрес: ул. Ленина 5")
    assert "учреждение: Школа 1" in suffix
    assert entity_suffix({}) == ""


def test_compose_communication_strategy():
    assert compose_communication_strategy({"quick_win": "A", "strategic": "B"}, "t") == "A B"
    assert compose_communication_strategy({"strategic": "B"}, "t") == "B"
    assert compose_communication_strategy({}, "тема") == "Сформировать публичный план решений по теме «тема»."


def test_severity_from_bucket_legacy_absolute():
    # total_mentions<=0 → legacy scoring; 5 упоминаний без доп.сигналов → low
    assert severity_from_bucket(_draft(mentions=5), total_mentions=0) == "low"


def test_severity_from_bucket_share_based():
    # доля 0.30 → critical, но потолок по упоминаниям (30 → high) → high
    assert severity_from_bucket(_draft(mentions=30), total_mentions=100) == "high"
    # высокая доля + много упоминаний → critical
    assert severity_from_bucket(_draft(mentions=60), total_mentions=200) == "critical"
    # мелкий pain с высокой долей → потолок роняет до low
    assert severity_from_bucket(_draft(mentions=3), total_mentions=5) == "low"


def test_severity_from_bucket_sentiment_escalation():
    # маленькая доля (base low), но ≥70% негатива и ≥5 упоминаний → эскалация до medium
    d = _draft(mentions=10, negative=8)
    assert severity_from_bucket(d, total_mentions=1000) == "medium"
