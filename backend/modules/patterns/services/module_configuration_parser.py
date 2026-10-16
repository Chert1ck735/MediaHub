import json
import re
from typing import Any

from backend.modules.patterns.errors import ModuleError


class ModuleConfigurationParser:
    """Достаёт и проверяет JSON-конфигурацию, вернувшуюся от LLM."""

    def parse(self, raw: str) -> dict[str, Any]:
        try:
            data = json.loads(self._extract_json_object(raw))
        except json.JSONDecodeError as exc:
            raise ModuleError("LLM вернул невалидный JSON configuration") from exc

        if not isinstance(data, dict):
            raise ModuleError("configuration должен быть JSON-объектом")

        return data

    def _extract_json_object(self, raw: str) -> str:
        text = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
        start = text.find("{")
        end = text.rfind("}")

        if start == -1 or end == -1 or end <= start:
            raise ModuleError("LLM не вернул JSON")

        return text[start : end + 1]
