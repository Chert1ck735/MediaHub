from datetime import date

import pytest
from pydantic import ValidationError

from backend.modules.llm.post_generation import build_generation_brief
from backend.modules.llm.prompt_builder import PromptBuilder
from backend.modules.llm.schemas import GeneratePostRequest


def test_generation_brief_uses_trusted_public_context_and_event_data():
    payload = GeneratePostRequest(
        public_social_link_id="8eb63971-5607-4191-895a-846d05c5b6fb",
        event_description="В субботу в парке состоится открытая встреча с жителями.",
        event_date=date(2026, 8, 30),
    )

    brief = build_generation_brief(
        payload,
        public_context={
            "name": "Администрация города",
            "description": "Официальные новости администрации города.",
            "audience": "Жители города",
            "goal": "Информировать жителей",
        },
    )

    assert brief["public_kind"] == "Паблик в социальной сети"
    assert brief["public_name"] == "Администрация города"
    assert brief["public_description"] == "Официальные новости администрации города."
    assert brief["event_description"] == payload.event_description
    assert brief["event_date"] == "2026-08-30"
    assert brief["post_type"] == ""


def test_generation_rejects_blank_event_description():
    with pytest.raises(ValidationError):
        GeneratePostRequest(
            public_social_link_id="8eb63971-5607-4191-895a-846d05c5b6fb",
            event_description="   ",
        )


def test_system_prompt_prioritizes_brief_facts_and_plain_text():
    prompt = PromptBuilder().system_prompt

    assert "единственные источники фактов о событии" in prompt
    assert "Не используй Markdown-разметку" in prompt
    assert "{example_input}" not in prompt
    assert "{example_output}" not in prompt
