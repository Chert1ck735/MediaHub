from abc import ABC, abstractmethod
from typing import Any, Protocol


class LLMError(RuntimeError):
    """Ошибка вызова языковой модели или разбора её ответа."""


class BaseLLMClient(ABC):
    """Общий интерфейс провайдеров языковых моделей."""

    @abstractmethod
    def generate(self, messages: list[dict]) -> str:
        raise NotImplementedError

    def count_tokens(self, text: str) -> int:
        raise NotImplementedError

    def close(self) -> None:
        pass


class LLMClientFactory(Protocol):
    def __call__(self, **kwargs: Any) -> BaseLLMClient:
        ...


class ModelResolver(Protocol):
    def __call__(self, provider: str | None = None) -> str:
        ...


class PromptRepository(Protocol):
    def load(self, relative_path: str) -> str:
        ...

    def render(self, relative_path: str, **context: Any) -> str:
        ...


class UsageMetricsReader(Protocol):
    def build_report(self, *, limit: int, since_hours: int) -> dict[str, Any]:
        ...


class PublicModuleReader(Protocol):
    async def list_for_public_link(
        self,
        *,
        public_social_link_id: str | None,
        organization_id: Any,
    ) -> list[dict[str, Any]]:
        ...

    async def get_generation_context(
        self,
        *,
        public_social_link_id: str,
        organization_id: Any,
    ) -> dict[str, Any]:
        ...
