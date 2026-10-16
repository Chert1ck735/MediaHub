from dataclasses import dataclass
from typing import Any, Callable

from backend.app.config import settings
from backend.modules.llm.clients import create_llm_client, get_default_llm_model
from backend.modules.llm.interfaces import LLMClientFactory, ModelResolver
from backend.modules.llm.post_generation import (
    build_generation_brief,
    build_generation_messages,
    enrich_brief_with_modules,
)
from backend.modules.llm.prompt_builder import PromptBuilder
from backend.modules.llm.schemas import GeneratePostRequest


@dataclass(frozen=True)
class PostGenerationResult:
    text: str
    model: str


class PostGenerationService:
    """Генерирует один текстовый пост по выбранному паблику и заданию."""

    def __init__(
        self,
        *,
        client_factory: LLMClientFactory = create_llm_client,
        model_resolver: ModelResolver = get_default_llm_model,
        prompt_builder_factory: Callable[[], PromptBuilder] = PromptBuilder,
    ):
        self.client_factory = client_factory
        self.model_resolver = model_resolver
        self.prompt_builder_factory = prompt_builder_factory

    def generate(
        self,
        payload: GeneratePostRequest,
        *,
        model: str | None = None,
        organization_modules: list[dict[str, Any]] | None = None,
        public_context: dict[str, Any] | None = None,
    ) -> PostGenerationResult:
        model_name = model or self.model_resolver(None)
        brief = enrich_brief_with_modules(
            build_generation_brief(payload, public_context=public_context),
            organization_modules=organization_modules,
        )
        builder = self.prompt_builder_factory()
        client = self.client_factory(
            model=model_name,
            num_predict=max(settings.OLLAMA_NUM_PREDICT_POST, 1100),
            usage_context="post_generation",
            temperature=0.35,
            top_p=0.85,
            top_k=40,
            repeat_penalty=1.08,
            think=False,
        )
        try:
            text = client.generate(
                build_generation_messages(
                    system_prompt=builder.for_post_type(payload.post_type),
                    brief=brief,
                )
            ).strip()
        finally:
            client.close()

        if not text:
            from backend.modules.llm.interfaces import LLMError

            raise LLMError("LLM returned an empty post")
        return PostGenerationResult(text=text, model=model_name)
