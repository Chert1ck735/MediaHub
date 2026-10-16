"""Ретраи классификации: backoff растёт экспоненциально, лимит хоронит запись."""
from datetime import datetime, timezone

from backend.db.comment_analysis import CommentAnalysis
from backend.modules.analytics.classification import (
    MAX_CLASSIFY_ATTEMPTS,
    RETRY_BACKOFF_CAP_S,
    STATE_FAILED,
    register_failed_attempt,
    retry_delay_s,
)


def test_retry_delay_grows_and_caps():
    delays = [retry_delay_s(n) for n in range(1, 8)]
    assert delays[0] == 300  # 5 минут
    assert all(b >= a for a, b in zip(delays, delays[1:]))
    assert delays[-1] == RETRY_BACKOFF_CAP_S


def test_register_failed_attempt_schedules_then_buries():
    now = datetime(2026, 8, 12, 12, 0, tzinfo=timezone.utc)
    analysis = CommentAnalysis(classification_attempts=0)

    for attempt in range(1, MAX_CLASSIFY_ATTEMPTS):
        register_failed_attempt(analysis, now=now)
        assert analysis.classification_state == STATE_FAILED
        assert analysis.classification_attempts == attempt
        assert analysis.next_attempt_at is not None
        assert analysis.next_attempt_at > now

    register_failed_attempt(analysis, now=now)
    assert analysis.classification_attempts == MAX_CLASSIFY_ATTEMPTS
    assert analysis.next_attempt_at is None  # окончательно


def test_backoff_schedule_is_reasonable():
    # первые попытки быстрые, хвост не превышает потолок
    assert retry_delay_s(1) == 300
    assert retry_delay_s(2) == 900
    assert retry_delay_s(3) == 2700
    assert retry_delay_s(10) == RETRY_BACKOFF_CAP_S
