import re


def normalize_hashtags(tags: list[str]) -> list[str]:
    """Нормализует хэштеги и ограничивает результат для текста поста."""

    normalized: list[str] = []
    for tag in tags:
        text = tag.strip()
        if not text:
            continue
        if not text.startswith("#"):
            text = "#" + text.replace(" ", "")
        normalized.append(text)
    return normalized[:4]


def split_sentences(text: str) -> list[str]:
    """Разбивает текст на простые фрагменты, похожие на предложения."""

    normalized = re.sub(r"\s+", " ", text).strip()
    if not normalized:
        return []
    parts = re.split(r"(?<=[.!?])\s+", normalized)
    return [part.strip(" -") for part in parts if part.strip(" -")]


def normalize_bullets(text: str) -> list[str]:
    """Преобразует многострочный призыв к действию в очищенные кандидаты для пунктов."""

    lines = [line.strip(" -\t") for line in text.splitlines()]
    return [line for line in lines if line]
