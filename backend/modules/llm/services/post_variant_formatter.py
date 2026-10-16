from pydantic import BaseModel, Field

from backend.modules.llm.utils.text_formatting import (
    normalize_bullets,
    normalize_hashtags,
    split_sentences,
)


class PostVariantDraft(BaseModel):
    angle: str = ""
    headline: str = ""
    hook: str = ""
    body: str = ""
    cta: str = ""
    hashtags: list[str] = Field(default_factory=list)
    full_text: str = ""


class PostVariantFormatter:
    """Форматирует и оценивает варианты постов, вернувшиеся от модели."""

    def format_text(self, variant: PostVariantDraft) -> str:
        headline = variant.headline.strip()
        lead_parts = [
            part.strip()
            for part in [variant.hook, variant.body]
            if part.strip()
        ]
        lead_text = "\n\n".join(lead_parts).strip()

        bullets: list[str] = []
        if variant.cta.strip():
            bullets.extend(normalize_bullets(variant.cta))

        if not bullets:
            sentences = split_sentences(lead_text)
            if len(sentences) > 1:
                bullets = sentences[-2:]
            elif sentences:
                bullets = [sentences[0]]

        hashtags = " ".join(normalize_hashtags(variant.hashtags))
        sections: list[str] = []
        if headline:
            sections.append(headline)
        if lead_text:
            sections.append(lead_text)
        if bullets:
            sections.append("\n".join(f"- {bullet}" for bullet in bullets[:3]))
        if hashtags:
            sections.append(hashtags)
        return "\n\n".join(section for section in sections if section).strip()

    def join_text(self, variant: PostVariantDraft) -> str:
        structured_text = self.format_text(variant)
        if structured_text:
            return structured_text

        if variant.full_text.strip():
            return variant.full_text.strip()

        pieces = [
            variant.headline.strip(),
            variant.hook.strip(),
            variant.body.strip(),
            variant.cta.strip(),
        ]
        text = "\n\n".join(piece for piece in pieces if piece)
        hashtags = " ".join(normalize_hashtags(variant.hashtags))
        if hashtags:
            text = f"{text}\n\n{hashtags}" if text else hashtags
        return text.strip()

    def score(self, variant: PostVariantDraft, target_length: int) -> float:
        text = self.join_text(variant)
        score = 0.0
        if variant.headline.strip():
            score += 1.2
        if variant.hook.strip():
            score += 1.4
        if variant.cta.strip():
            score += 1.0
        hashtags = normalize_hashtags(variant.hashtags)
        if 2 <= len(hashtags) <= 4:
            score += 0.6
        length = len(text)
        if length:
            delta = abs(length - target_length)
            score += max(0.0, 2.2 - (delta / max(target_length, 1)) * 2.2)
        if "\n\n" in text:
            score += 0.4
        if any(ch.isdigit() for ch in text):
            score += 0.2
        return round(score, 3)
