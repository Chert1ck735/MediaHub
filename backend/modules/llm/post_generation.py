from __future__ import annotations

from typing import Any

from backend.modules.llm.prompt_loader import render_prompt
from backend.modules.llm.schemas import GeneratePostRequest


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def build_generation_brief(
    payload: GeneratePostRequest,
    *,
    public_context: dict[str, Any] | None = None,
) -> dict[str, str]:
    """Собирает краткое задание под текущий контракт генерации."""

    public_context = public_context or {}
    return {
        "public_kind": "Паблик в социальной сети",
        "public_name": _clean_text(public_context.get("name")),
        "public_description": _clean_text(public_context.get("description")),
        "public_audience": _clean_text(public_context.get("audience")),
        "public_goal": _clean_text(public_context.get("goal")),
        "event_description": payload.event_description,
        "event_date": payload.event_date.isoformat() if payload.event_date else "",
        "post_type": payload.post_type or "",
    }


def enrich_brief_with_modules(
    brief: dict[str, str],
    organization_modules: list[dict[str, Any]] | None = None,
) -> dict[str, str]:
    """Добавляет выбранный модуль паблика как справочный контекст, если он есть."""

    if not organization_modules:
        return brief

    notes: list[str] = []
    for module in organization_modules[:1]:
        parts = [
            _clean_text(module.get("name")),
            _clean_text(module.get("goal")),
            _clean_text(module.get("description")),
        ]
        configuration = module.get("configuration")
        if isinstance(configuration, dict):
            parts.extend(
                _clean_text(configuration.get(key))
                for key in ("summary", "topic", "target_audience", "generation_rules")
            )
        text = " | ".join(part for part in parts if part)
        if text:
            notes.append(text[:4_000])

    if not notes:
        return brief
    return {**brief, "public_module_context": "\n".join(notes)}


def build_generation_messages(
    *,
    system_prompt: str,
    brief: dict[str, str],
) -> list[dict[str, str]]:
    lines = [f"{key}: {value}" for key, value in brief.items() if value]
    return [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": render_prompt(
                "builder/post_user.md",
                brief="\n".join(lines),
            ),
        },
    ]
