from __future__ import annotations

import uuid
from importlib import import_module
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy.dialects import postgresql

from backend.modules.analytics import classification

analytics_router = import_module("backend.modules.analytics.router")


UTC = timezone.utc


def test_rate_handles_equal_timestamps_as_worker_batches() -> None:
    now = datetime(2026, 8, 19, 12, 0, tzinfo=UTC)
    first_batch = [now - timedelta(minutes=1)] * 50
    second_batch = [now] * 50

    rate, source, window, sample_size = classification.estimate_completion_rate(
        [*first_batch, *second_batch],
        now=now,
    )

    assert rate == pytest.approx(50.0)
    assert source == "recent"
    assert window == 60
    assert sample_size == 100


def test_recent_rate_ignores_an_old_run_and_uses_completed_batch_interval() -> None:
    now = datetime(2026, 8, 19, 12, 0, tzinfo=UTC)
    old_run = [now - timedelta(hours=1)] * 100
    recent_first = [now - timedelta(minutes=2)] * 10
    recent_second = [now - timedelta(minutes=1)] * 10

    rate, source, window, sample_size = classification.estimate_completion_rate(
        [*old_run, *recent_first, *recent_second],
        now=now,
    )

    # Ten completions since the baseline batch over one measured minute.  The
    # idle minute after the last batch and the old run must not distort it.
    assert rate == pytest.approx(10.0)
    assert source == "recent"
    assert window == 60
    assert sample_size == 20


def test_historical_contiguous_run_is_cold_start_fallback() -> None:
    now = datetime(2026, 8, 19, 12, 0, tzinfo=UTC)
    first = [now - timedelta(minutes=30)] * 4
    second = [now - timedelta(minutes=29, seconds=30)] * 4

    rate, source, window, sample_size = classification.estimate_completion_rate(
        [*first, *second],
        now=now,
    )

    assert rate == pytest.approx(8.0)
    assert source == "historical"
    assert window == 30
    assert sample_size == 8


def test_single_batch_does_not_invent_throughput_from_its_size() -> None:
    now = datetime(2026, 8, 19, 12, 0, tzinfo=UTC)

    single = classification.estimate_completion_rate(
        [now - timedelta(minutes=2)] * 50,
        now=now,
    )
    empty = classification.estimate_completion_rate([], now=now)

    assert single == (1.0, "single_batch_default", 0, 50)
    assert empty == (1.0, "default", 0, 0)


def test_slow_batches_more_than_ten_minutes_apart_still_measure_real_rate() -> None:
    now = datetime(2026, 8, 19, 12, 0, tzinfo=UTC)
    timestamps = [now - timedelta(minutes=20)] * 50 + [now] * 50

    rate, source, window, sample_size = classification.estimate_completion_rate(
        timestamps,
        now=now,
    )

    assert rate == pytest.approx(2.5)
    assert source == "historical"
    assert window == 20 * 60
    assert sample_size == 100


def test_completion_query_is_tenant_scoped_and_excludes_non_completions() -> None:
    organization_id = uuid.uuid4()
    stmt = classification._classification_completion_timestamps_query(organization_id)
    sql = str(
        stmt.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    ).lower()

    assert str(organization_id) in sql
    assert "publics.organization_id" in sql
    assert "comments.is_deleted is false" in sql
    assert "classification_state = 'done'" in sql
    assert "llm_manual" in sql
    assert "rule_based" in sql

    retry_sql = str(
        classification._latest_retry_at_query(organization_id).compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    ).lower()
    assert str(organization_id) in retry_sql
    assert "publics.organization_id" in retry_sql
    assert "comments.is_deleted is false" in retry_sql
    assert "classification_state = 'failed'" in retry_sql
    assert "next_attempt_at is not null" in retry_sql


class _Rows:
    def __init__(self, timestamps: list[datetime]) -> None:
        self._timestamps = timestamps

    def all(self):
        return [(timestamp,) for timestamp in self._timestamps]


class _Db:
    def __init__(self, timestamps: list[datetime]) -> None:
        self.timestamps = timestamps

    async def execute(self, _stmt):
        return _Rows(self.timestamps)


class _Scalar:
    def __init__(self, value: datetime | None) -> None:
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class _DbWithRetry(_Db):
    def __init__(self, timestamps: list[datetime], latest_retry_at: datetime) -> None:
        super().__init__(timestamps)
        self.latest_retry_at = latest_retry_at
        self.calls = 0

    async def execute(self, _stmt):
        self.calls += 1
        if self.calls == 1:
            return _Rows(self.timestamps)
        return _Scalar(self.latest_retry_at)


@pytest.mark.asyncio
async def test_queue_performance_eta_uses_all_remaining_work() -> None:
    now = datetime(2026, 8, 19, 12, 0, tzinfo=UTC)
    timestamps = [now - timedelta(minutes=1)] * 5 + [now] * 5

    performance = await classification.estimate_queue_performance(
        _Db(timestamps),
        organization_id=uuid.uuid4(),
        remaining=13,
        now=now,
    )

    assert performance.rate_per_minute == pytest.approx(5.0)
    assert performance.eta_minutes == 3
    assert performance.rate_source == "recent"


@pytest.mark.asyncio
async def test_queue_performance_eta_waits_for_scheduled_retry_tail() -> None:
    now = datetime(2026, 8, 19, 12, 0, tzinfo=UTC)
    timestamps = [now - timedelta(minutes=1)] * 5 + [now] * 5
    db = _DbWithRetry(timestamps, latest_retry_at=now + timedelta(minutes=10))

    performance = await classification.estimate_queue_performance(
        db,
        organization_id=uuid.uuid4(),
        remaining=13,
        failed_retrying=3,
        now=now,
    )

    # Base ETA is 13/5 = 2.6 min.  The last retry cannot even start for ten
    # minutes and its retry tail takes another 3/5 min, hence ceil(10.6) = 11.
    assert performance.rate_per_minute == pytest.approx(5.0)
    assert performance.eta_minutes == 11
    assert db.calls == 2


@pytest.mark.asyncio
async def test_queue_endpoint_includes_retrying_in_remaining(monkeypatch) -> None:
    organization_id = uuid.uuid4()
    captured: dict[str, int] = {}

    async def counts(*_args, **_kwargs):
        return {
            "pending": 4,
            "processing": 2,
            "done": 10,
            "failed": 5,
            "failed_retrying": 3,
        }

    async def performance(*_args, remaining: int, **_kwargs):
        captured["remaining"] = remaining
        return classification.QueuePerformance(2.0, 5, "recent", 120, 6)

    async def empty(*_args, **_kwargs):
        return []

    async def zero(*_args, **_kwargs):
        return 0

    async def healthy():
        return True

    monkeypatch.setattr(classification, "count_classification_states", counts)
    monkeypatch.setattr(classification, "count_queue_by_public", empty)
    monkeypatch.setattr(classification, "count_manual_review", zero)
    monkeypatch.setattr(classification, "estimate_queue_performance", performance)
    monkeypatch.setattr(analytics_router.llm_coordination, "is_worker_paused", lambda: False)
    monkeypatch.setattr(analytics_router.llm_health, "llm_reachable", healthy)

    payload = await analytics_router.classification_queue(
        current_user=SimpleNamespace(organization_id=organization_id),
        db=object(),
    )

    assert captured["remaining"] == 9
    assert payload["remaining"] == 9
    assert payload["in_progress"] == 6
    assert payload["eta_minutes"] == 5
    assert payload["rate_per_minute"] == 2.0


@pytest.mark.asyncio
async def test_empty_queue_eta_is_zero_even_without_history() -> None:
    performance = await classification.estimate_queue_performance(
        _Db([]),
        organization_id=uuid.uuid4(),
        remaining=0,
        now=datetime(2026, 8, 19, 12, 0, tzinfo=UTC),
    )

    assert performance.rate_per_minute == 1.0
    assert performance.eta_minutes == 0
    assert performance.rate_source == "default"
