"""Structured output реально уходит в запрос — и корректно откатывается.

Сетевого вызова нет: подменяем транспорт и смотрим, что клиент положил в запрос.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.modules.llm.analysis_schema import build_analysis_json_schema
from backend.modules.llm.interfaces import LLMError
from backend.modules.llm.providers.ollama_client import QwenClient
from backend.modules.llm.providers.openai_compatible_client import OpenAICompatibleClient

_MESSAGES = [{"role": "user", "content": "тест"}]


def _fake_completion(text: str = '{"ok": true}'):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=text))],
        usage=None,
    )


class _RecordingCompletions:
    """Записывает kwargs и, по желанию, падает на первом вызове со схемой."""

    def __init__(self, fail_on_schema: bool = False):
        self.calls: list[dict] = []
        self.fail_on_schema = fail_on_schema

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.fail_on_schema and "response_format" in kwargs:
            raise ValueError("400: response_format is not supported by this server")
        return _fake_completion()


def _openai_client(fail_on_schema: bool = False) -> tuple[OpenAICompatibleClient, _RecordingCompletions]:
    client = OpenAICompatibleClient(
        model="test-model",
        response_schema=build_analysis_json_schema(),
        response_schema_name="comment_analysis",
    )
    recorder = _RecordingCompletions(fail_on_schema=fail_on_schema)
    client.client = SimpleNamespace(chat=SimpleNamespace(completions=recorder))
    return client, recorder


def test_openai_client_sends_json_schema():
    client, recorder = _openai_client()

    client.generate(_MESSAGES)

    assert len(recorder.calls) == 1
    response_format = recorder.calls[0]["response_format"]
    assert response_format["type"] == "json_schema"
    assert response_format["json_schema"]["name"] == "comment_analysis"
    assert response_format["json_schema"]["strict"] is True
    # enum таксономии доехал до сервера
    category = response_format["json_schema"]["schema"]["properties"]["hierarchy"][
        "properties"
    ]["category"]
    assert "ЖКХ и городская среда" in category["enum"]


def test_openai_client_falls_back_when_server_rejects_schema():
    """Сервер без constrained decoding не должен ронять классификацию."""

    client, recorder = _openai_client(fail_on_schema=True)

    text = client.generate(_MESSAGES)

    assert text == '{"ok": true}'
    assert len(recorder.calls) == 2                      # со схемой, затем без
    assert "response_format" in recorder.calls[0]
    assert "response_format" not in recorder.calls[1]
    assert client._structured_output_supported is False  # больше не пробуем


def test_openai_client_stops_retrying_after_fallback():
    client, recorder = _openai_client(fail_on_schema=True)

    client.generate(_MESSAGES)
    client.generate(_MESSAGES)

    # Второй вызов уже не тратит попытку на схему.
    assert len(recorder.calls) == 3
    assert "response_format" not in recorder.calls[2]


def test_openai_client_reraises_unrelated_errors():
    """Обычная ошибка сервера не должна маскироваться под «схема не поддержана»."""

    client, recorder = _openai_client()

    def boom(**kwargs):
        recorder.calls.append(kwargs)
        raise ValueError("connection reset by peer")

    client.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=boom)))

    with pytest.raises(LLMError):
        client.generate(_MESSAGES)
    assert len(recorder.calls) == 1  # без повтора


def test_ollama_client_sends_format_schema():
    schema = build_analysis_json_schema()
    client = QwenClient(model="test-model", response_schema=schema)

    payload = client._with_common_payload({"model": "test-model"})

    assert payload["format"] == schema


def test_ollama_client_omits_format_without_schema():
    client = QwenClient(model="test-model")

    payload = client._with_common_payload({"model": "test-model"})

    assert "format" not in payload


@pytest.mark.asyncio
async def test_analysis_service_passes_schema_to_factory():
    """Последнее звено: сервис классификации действительно включает схему."""

    from backend.modules.llm.services.comment_analysis_service import (
        CommentAnalysisService,
    )

    captured: dict = {}

    class _Client:
        def generate(self, messages):
            return (
                '{"relevance":"relevant","author_type":"citizen",'
                '"message_type":"complaint","sentiment":"negative",'
                '"is_official_response":false,'
                '"hierarchy":{"category":"Дороги и транспорт","subcategory":"","case":""},'
                '"entities":{"address":null,"institution":null,'
                '"reference_number":null,"deadline":null},'
                '"summary":"яма","confidence":0.8,"candidates":[]}'
            )

        def close(self):
            pass

    def _factory(**kwargs):
        captured.update(kwargs)
        return _Client()

    service = CommentAnalysisService(client_factory=_factory)
    result = await service.analyze("Яма на дороге")

    assert captured["response_schema_name"] == "comment_analysis"
    assert captured["response_schema"]["properties"]["confidence"]["type"] == "number"
    assert result.confidence == 0.8
