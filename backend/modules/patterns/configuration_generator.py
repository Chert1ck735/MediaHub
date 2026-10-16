"""Compatibility facade for module configuration generation."""

from __future__ import annotations

from typing import Any

from backend.modules.llm.clients import LLMError, create_llm_client
from backend.modules.patterns.errors import ModuleError
from backend.modules.patterns.interfaces import (
    ConfigurationParser,
    LLMClientFactory,
)
from backend.modules.patterns.services.module_configuration_parser import (
    ModuleConfigurationParser,
)
from backend.modules.patterns.services.module_prompt_builder import (
    ModuleConfigurationPromptBuilder,
)


class ModuleConfigurationGenerator:
    """Связывает сборку промпта, вызов LLM и разбор конфигурации."""

    def __init__(
        self,
        *,
        client_factory: LLMClientFactory = create_llm_client,
        prompt_builder: ModuleConfigurationPromptBuilder | None = None,
        parser: ConfigurationParser | None = None,
    ):
        self.client_factory = client_factory
        self.prompt_builder = prompt_builder or ModuleConfigurationPromptBuilder()
        self.parser = parser or ModuleConfigurationParser()

    def generate(self, context_text: str) -> dict[str, Any]:
        client = self.client_factory(
            usage_context="module_configuration",
            temperature=0.2,
        )
        try:
            raw = client.generate(self.prompt_builder.build_messages(context_text))
        except LLMError as exc:
            raise ModuleError(
                f"Не удалось сгенерировать configuration через LLM: {exc}"
            ) from exc
        finally:
            client.close()

        return self.parser.parse(raw)
