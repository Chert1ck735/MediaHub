"""Выбранной модели может не быть на сервере — это надо называть прямо."""
import json

import pytest

from backend.app.config import settings
from backend.modules.analytics import llm_health


class _Response:
    def __init__(self, payload):
        self._payload = payload

    def read(self):
        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _models(*ids):
    return {"object": "list", "data": [{"id": name} for name in ids]}


@pytest.fixture
def server(monkeypatch):
    """Подменяет ответ сервера моделей."""

    def _setup(payload=None, error: Exception | None = None):
        def fake_urlopen(url, timeout=None):
            if error is not None:
                raise error
            return _Response(payload)

        monkeypatch.setattr(llm_health.urllib.request, "urlopen", fake_urlopen)

    return _setup


@pytest.fixture(autouse=True)
def openai_provider(monkeypatch):
    monkeypatch.setattr(settings, "LLM_PROVIDER", "openai")
    monkeypatch.setattr(settings, "OPENAI_COMPATIBLE_BASE_URL", "http://llm:9012/v1")
    monkeypatch.setattr(
        settings,
        "OPENAI_COMPATIBLE_MODEL",
        "huggingface.co/unsloth/qwen3.6-35b-a3b-gguf:Q4_K_M",
    )


def test_model_on_server_is_not_a_problem(server):
    server(_models("huggingface.co/unsloth/qwen3.6-35b-a3b-gguf:Q4_K_M"))

    assert llm_health.configured_model_problem() is None


def test_missing_model_names_itself_and_the_alternatives(server):
    """Случай с прода: в настройках тег Q4_K_M, на сервере лежит UD-Q2_K_XL."""

    server(_models(
        "huggingface.co/unsloth/qwen3.6-35b-a3b-gguf:UD-Q2_K_XL",
        "docker.io/ai/qwen3.6-a3b:Q4_K_M",
    ))

    problem = llm_health.configured_model_problem()

    assert problem is not None
    assert "qwen3.6-35b-a3b-gguf:Q4_K_M" in problem
    assert "UD-Q2_K_XL" in problem


def test_unreachable_server_is_not_reported_here(server):
    """Недоступность показывает llm_reachable, дублировать её незачем."""

    server(error=OSError("connection refused"))

    assert llm_health.configured_model_problem() is None


def test_ollama_is_not_checked(server, monkeypatch):
    monkeypatch.setattr(settings, "LLM_PROVIDER", "ollama")
    server(_models("ничего подходящего"))

    assert llm_health.configured_model_problem() is None
