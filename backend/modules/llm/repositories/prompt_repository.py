from typing import Any

from backend.modules.llm.prompt_loader import load_prompt, render_prompt


class FilePromptRepository:
    """Читает шаблоны промптов из каталога llm."""

    def load(self, relative_path: str) -> str:
        return load_prompt(relative_path)

    def render(self, relative_path: str, **context: Any) -> str:
        return render_prompt(relative_path, **context)
