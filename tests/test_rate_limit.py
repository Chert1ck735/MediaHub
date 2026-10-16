"""Юнит-тесты для RateLimiter — без БД, без HTTP."""
from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException

from backend.app.rate_limit import RateLimiter


async def test_under_limit_passes():
    rl = RateLimiter(max_calls=3, window_seconds=10)
    for _ in range(3):
        await rl.check_async("user1")


async def test_over_limit_raises_429():
    rl = RateLimiter(max_calls=3, window_seconds=10)
    for _ in range(3):
        await rl.check_async("user1")
    with pytest.raises(HTTPException) as ei:
        await rl.check_async("user1")
    assert ei.value.status_code == 429
    assert "Retry-After" in ei.value.headers


async def test_window_resets_after_expiry():
    rl = RateLimiter(max_calls=2, window_seconds=1)
    await rl.check_async("u")
    await rl.check_async("u")
    with pytest.raises(HTTPException):
        await rl.check_async("u")
    await asyncio.sleep(1.05)
    # после окна — снова можно
    await rl.check_async("u")


async def test_different_keys_are_isolated():
    rl = RateLimiter(max_calls=2, window_seconds=10)
    await rl.check_async("a")
    await rl.check_async("a")
    # для другого ключа лимит свой
    await rl.check_async("b")
    await rl.check_async("b")
    with pytest.raises(HTTPException):
        await rl.check_async("a")
    with pytest.raises(HTTPException):
        await rl.check_async("b")


async def test_different_routes_are_isolated():
    rl = RateLimiter(max_calls=1, window_seconds=10)
    await rl.check_async("user", route="r1")
    await rl.check_async("user", route="r2")
    # тот же user, тот же лимитер, но разные routes — лимит на route
    with pytest.raises(HTTPException):
        await rl.check_async("user", route="r1")
