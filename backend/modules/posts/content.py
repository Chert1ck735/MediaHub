"""Работа с текстовым содержимым поста."""

from backend.db.posts import Post


def extract_post_tone(post: Post) -> str:
    """Достает тон из первой строки text_final, если он там записан."""
    text_final = post.text_final or ""
    if not text_final.startswith("[тон:"):
        return ""
    first_line = text_final.split("\n", 1)[0]
    return first_line.removeprefix("[тон: ").removesuffix("]")


def build_text_final(text_generated: str, tone: str) -> str:
    """Собирает финальный текст поста, добавляя служебную строку тона."""
    return f"[тон: {tone}]\n{text_generated}" if tone else text_generated


def post_summary(text_generated: str | None, text_draft: str | None) -> str | None:
    """Строит короткое summary из сгенерированного или чернового текста."""
    return ((text_generated or text_draft or "")[:500] or None)

