from __future__ import annotations

from backend.modules.llm.prompt_loader import load_prompt, render_prompt


SYSTEM = load_prompt("analysis/system.md")


def get_analyze_prompt(
        text: str
) -> str:
    """Собирает пользовательский промпт анализа комментария из шаблона разметки."""
    return render_prompt("analysis/user.md", text=text)
