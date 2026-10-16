"""Всплеск — только при достаточном объёме и росте ≥ ×1.5."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.modules.analytics.services.alerts_service import AlertsService, is_spike


class _StubResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _StubDb:
    """Подменяет выполнение SQL: проверяем решения на питоне, не в Postgres."""

    def __init__(self, rows):
        self._rows = rows

    async def execute(self, *_args, **_kwargs):
        return _StubResult(self._rows)


def _row(cat: str, recent: int, prior: int, covered: bool = True):
    return SimpleNamespace(cat=cat, recent=recent, prior=prior, covered=covered)


_USER = SimpleNamespace(organization_id="org-1")


def test_growth_over_threshold_is_spike():
    assert is_spike(recent=12, prior=4)


def test_below_min_recent_is_not_spike():
    assert not is_spike(recent=4, prior=0)


def test_flat_or_declining_is_not_spike():
    assert not is_spike(recent=6, prior=6)
    assert not is_spike(recent=6, prior=10)


def test_growth_from_zero_counts_when_volume_enough():
    assert is_spike(recent=5, prior=0)


def test_small_growth_not_spike():
    assert not is_spike(recent=6, prior=5)


@pytest.mark.asyncio
async def test_tiny_prior_gives_no_percentage():
    """Регрессия: prior=1, recent=27 давали «+2600%» на свежем паблике."""

    service = AlertsService(_StubDb([_row("ЖКХ", recent=27, prior=1)]))

    alerts = await service.alerts(_USER)

    assert len(alerts) == 1
    assert alerts[0]["recent"] == 27
    assert alerts[0]["growth_pct"] is None  # число было бы шумом


@pytest.mark.asyncio
async def test_percentage_shown_when_prior_is_solid():
    service = AlertsService(_StubDb([_row("ЖКХ", recent=30, prior=10)]))

    alerts = await service.alerts(_USER)

    assert alerts[0]["growth_pct"] == 200


@pytest.mark.asyncio
async def test_uncovered_prior_window_yields_no_alerts():
    """История не покрывает прошлое окно — сравнивать не с чем."""

    service = AlertsService(_StubDb([_row("ЖКХ", recent=27, prior=1, covered=False)]))

    assert await service.alerts(_USER) == []
