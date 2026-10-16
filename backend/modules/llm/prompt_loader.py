from __future__ import annotations

from functools import lru_cache
from pathlib import Path


PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"


@lru_cache(maxsize=128)
def load_prompt(relative_path: str) -> str:
    """Читает промпт с разметкой из папки промптов и кэширует результат."""
    path = (PROMPTS_DIR / relative_path).resolve()
    prompts_root = PROMPTS_DIR.resolve()

    if not path.is_relative_to(prompts_root):
        raise ValueError(f"Недопустимый путь к prompt-файлу: {relative_path!r}")

    return path.read_text(encoding="utf-8-sig").strip()


def render_prompt(relative_path: str, **values: object) -> str:
    """Загружает шаблон с разметкой и подставляет переданные значения."""
    return load_prompt(relative_path).format(**values)
