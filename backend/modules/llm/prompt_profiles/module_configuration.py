from __future__ import annotations

from backend.modules.llm.prompt_loader import load_prompt, render_prompt


SYSTEM = load_prompt("module/system.md")


def get_module_generation_prompt(text: str) -> str:
    """Собирает пользовательский промпт генерации конфигурации модуля."""

    return render_prompt("module/user.md", text=text)

