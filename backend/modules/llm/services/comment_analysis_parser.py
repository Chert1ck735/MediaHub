import json

from pydantic import ValidationError

from backend.modules.llm.interfaces import LLMError
from backend.modules.llm.schemas import CommentAnalysisResponse
from backend.modules.llm.utils.json_response import extract_json_object


class CommentAnalysisParser:
    """Разбирает и проверяет структурированные ответы разбора комментариев."""

    def parse(self, raw_response: str) -> CommentAnalysisResponse:
        full_response = (
            raw_response
            if raw_response.lstrip().startswith("{")
            else "{" + raw_response
        )
        try:
            payload = json.loads(extract_json_object(full_response))
            return CommentAnalysisResponse.model_validate(payload)
        except (json.JSONDecodeError, ValidationError, ValueError, LLMError):
            raise
