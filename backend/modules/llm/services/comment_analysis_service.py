import asyncio
import json
import time

from pydantic import ValidationError

from backend.app.config import settings
from backend.modules.llm import analysis_prompt
from backend.modules.llm.analysis_schema import SCHEMA_NAME, build_analysis_json_schema
from backend.modules.llm.clients import create_llm_client, get_default_llm_model
from backend.modules.llm.interfaces import (
    BaseLLMClient,
    LLMClientFactory,
    LLMError,
    ModelResolver,
    PromptRepository,
)
from backend.modules.llm.repositories.prompt_repository import FilePromptRepository
from backend.modules.llm.schemas import CommentAnalysisResponse
from backend.modules.llm.services.comment_analysis_parser import CommentAnalysisParser


class CommentAnalysisService:
    """Ведёт классификацию импортированных комментариев через LLM."""

    def __init__(
        self,
        *,
        client_factory: LLMClientFactory = create_llm_client,
        model_resolver: ModelResolver = get_default_llm_model,
        prompt_repository: PromptRepository | None = None,
        parser: CommentAnalysisParser | None = None,
    ):
        self.client_factory = client_factory
        self.model_resolver = model_resolver
        self.prompt_repository = prompt_repository or FilePromptRepository()
        self.parser = parser or CommentAnalysisParser()

    async def analyze(
        self,
        text: str,
        *,
        model: str | None = None,
        temperature: float | None = None,
        top_p: float | None = None,
        top_k: int | None = None,
        repeat_penalty: float | None = None,
        system_prompt_template: str | None = None,
    ) -> CommentAnalysisResponse:
        model_name = model or self.model_resolver(None)
        client = self.client_factory(
            model=model_name,
            num_predict=settings.OLLAMA_NUM_PREDICT_ANALYTICS,
            usage_context="comment_analysis",
            temperature=0.1 if temperature is None else temperature,
            top_p=1.0 if top_p is None else top_p,
            top_k=20 if top_k is None else top_k,
            repeat_penalty=1.02 if repeat_penalty is None else repeat_penalty,
            think=False,
            # Constrained decoding: рантайм физически не даёт модели вернуть
            # невалидный JSON или категорию вне таксономии.
            response_schema=(
                build_analysis_json_schema()
                if settings.LLM_STRUCTURED_OUTPUT
                else None
            ),
            response_schema_name=SCHEMA_NAME,
        )
        try:
            return await asyncio.to_thread(
                self._analyze_with_client,
                client,
                text,
                system_prompt_template
            )
        finally:
            client.close()

    def _analyze_with_client(
        self,
        client: BaseLLMClient,
        text: str,
        system_prompt_template: str | None = None
    ) -> CommentAnalysisResponse:

        if system_prompt_template:
            system_prompt = self.prompt_repository.load(system_prompt_template)
        else:
            system_prompt = analysis_prompt.SYSTEM

        base_messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": analysis_prompt.get_analyze_prompt(text)},
            {
                "role": "assistant",
                "content": self.prompt_repository.load("analysis/assistant_prefix.md"),
            },
        ]
        messages = list(base_messages)
        last_error: Exception | None = None
        last_raw_response = ""

        for attempt in range(3):
            try:
                raw_response = client.generate(messages)
                last_raw_response = raw_response
                return self.parser.parse(raw_response)
            except LLMError as exc:
                last_error = exc
                if attempt < 2:
                    time.sleep(0.5 * (attempt + 1))
            except (json.JSONDecodeError, ValidationError, ValueError) as exc:
                last_error = exc
                messages = [
                    *base_messages,
                    {
                        "role": "user",
                        "content": self.prompt_repository.load("analysis/retry_user.md"),
                    },
                    {
                        "role": "assistant",
                        "content": self.prompt_repository.load(
                            "analysis/assistant_prefix.md"
                        ),
                    },
                ]

        raise LLMError(
            "Failed to parse comment analysis response after retries: "
            f"{last_error}. Raw: {last_raw_response}"
        ) from last_error
