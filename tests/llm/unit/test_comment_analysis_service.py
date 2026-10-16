"""Тесты ретраев LLM-классификации комментариев."""
from __future__ import annotations

import pytest

from backend.modules.llm.interfaces import LLMError
from backend.modules.llm.services.comment_analysis_service import CommentAnalysisService


class _FakeClient:
    """Отдаёт поведения по очереди: исключение → raise, строка → вернуть."""

    def __init__(self, behaviors):
        self.behaviors = list(behaviors)
        self.calls = 0

    def generate(self, messages):
        self.calls += 1
        behavior = self.behaviors.pop(0)
        if isinstance(behavior, Exception):
            raise behavior
        return behavior

    def close(self):
        pass


class _FixedParser:
    def __init__(self, result):
        self.result = result

    def parse(self, raw):
        return self.result


class _FailingParser:
    def parse(self, raw):
        raise ValueError("невалидный JSON")


def _service(client, parser):
    return CommentAnalysisService(
        client_factory=lambda **_: client,
        model_resolver=lambda _: "test-model",
        parser=parser,
    )


@pytest.mark.asyncio
async def test_network_error_is_retried_then_succeeds(monkeypatch):
    import backend.modules.llm.services.comment_analysis_service as mod

    monkeypatch.setattr(mod.time, "sleep", lambda _s: None)
    sentinel = object()
    client = _FakeClient([LLMError("timeout"), LLMError("timeout"), "ok"])

    result = await _service(client, _FixedParser(sentinel)).analyze("текст")

    assert result is sentinel
    assert client.calls == 3


@pytest.mark.asyncio
async def test_persistent_failure_raises_after_three_attempts(monkeypatch):
    import backend.modules.llm.services.comment_analysis_service as mod

    monkeypatch.setattr(mod.time, "sleep", lambda _s: None)
    client = _FakeClient([LLMError("timeout"), LLMError("timeout"), LLMError("timeout")])

    with pytest.raises(LLMError):
        await _service(client, _FixedParser(object())).analyze("текст")

    assert client.calls == 3


@pytest.mark.asyncio
async def test_invalid_json_is_retried_with_nudge():
    client = _FakeClient(["bad", "bad", "bad"])

    with pytest.raises(LLMError):
        await _service(client, _FailingParser()).analyze("текст")

    assert client.calls == 3
