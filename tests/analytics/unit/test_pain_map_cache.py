"""Кэш геокода: валидный хит, TTL промаха, старый None-формат перезапрашивается."""
from __future__ import annotations

from backend.modules.analytics.services.pain_map_service import _is_hit, _miss_fresh


def test_hit_is_dict_with_coords():
    assert _is_hit({"lat": 56.0, "lon": 92.8, "district": "Центральный"})
    assert not _is_hit({"_miss": 100.0})
    assert not _is_hit(None)


def test_fresh_miss_is_not_retried():
    assert _miss_fresh({"_miss": 1000.0}, now=1000.0 + 10, ttl=86400)


def test_stale_miss_is_retried():
    assert not _miss_fresh({"_miss": 1000.0}, now=1000.0 + 90000, ttl=86400)


def test_legacy_none_miss_is_retried():
    assert not _miss_fresh(None, now=1000.0, ttl=86400)
