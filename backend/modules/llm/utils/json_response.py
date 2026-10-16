import json
import re

from backend.modules.llm.clients import LLMError


def _scan_forward(text: str, start: int) -> str | None:
    """Находит сбалансированный структурированный объект, начиная с заданного индекса."""

    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


def extract_json_object(raw_response: str) -> str:
    """Извлекает первый валидный структурированный объект из сырого ответа модели."""

    text = re.sub(r"<think>.*?</think>", "", raw_response, flags=re.DOTALL).strip()
    i = 0
    last_candidate: str | None = None
    while i < len(text):
        if text[i] == "{":
            candidate = _scan_forward(text, i)
            if candidate is not None:
                last_candidate = candidate
                try:
                    json.loads(candidate)
                    return candidate
                except json.JSONDecodeError:
                    pass
        i += 1

    if last_candidate is not None:
        return last_candidate
    raise LLMError(f"Failed to find JSON payload in LLM response: {raw_response}")
