from backend.app.config import settings
from backend.modules.llm.interfaces import BaseLLMClient, LLMError
from backend.modules.llm.providers.ollama_client import QwenClient
from backend.modules.llm.providers.openai_compatible_client import OpenAICompatibleClient


def _normalize_provider(provider: str | None = None) -> str:
    normalized = (provider or settings.LLM_PROVIDER).strip().lower()
    if normalized in {"openai", "openai_compatible", "openai-compatible"}:
        return "openai"
    if normalized == "ollama":
        return "ollama"
    raise LLMError(f"Unsupported LLM provider: {normalized}")


def get_default_llm_model(provider: str | None = None) -> str:
    normalized = _normalize_provider(provider)
    if normalized == "openai":
        return settings.OPENAI_COMPATIBLE_MODEL
    if normalized == "ollama":
        return settings.OLLAMA_MODEL


def create_llm_client(
    *,
    model: str | None = None,
    timeout: int | None = None,
    num_predict: int | None = None,
    temperature: float = 0.6,
    top_p: float = 0.9,
    top_k: int = 40,
    repeat_penalty: float = 1.1,
    think: bool | None = False,
    usage_context: str | None = None,
    provider: str | None = None,
    response_schema: dict | None = None,
    response_schema_name: str = "response",
) -> BaseLLMClient:
    """``response_schema`` включает constrained decoding: рантайм не даёт модели
    выйти за схему прямо во время генерации."""

    normalized = _normalize_provider(provider)

    if normalized == "openai":
        return OpenAICompatibleClient(
            model=model or settings.OPENAI_COMPATIBLE_MODEL,
            timeout=timeout or settings.OPENAI_COMPATIBLE_TIMEOUT,
            num_predict=num_predict,
            temperature=temperature,
            top_p=top_p,
            top_k=top_k,
            repeat_penalty=repeat_penalty,
            think=think,
            base_url=settings.OPENAI_COMPATIBLE_BASE_URL,
            api_key=settings.OPENAI_COMPATIBLE_API_KEY,
            usage_context=usage_context,
            response_schema=response_schema,
            response_schema_name=response_schema_name,
        )

    if normalized == "ollama":
        return QwenClient(
            model=model or settings.OLLAMA_MODEL,
            timeout=timeout or settings.OLLAMA_TIMEOUT,
            num_predict=num_predict,
            temperature=temperature,
            top_p=top_p,
            top_k=top_k,
            repeat_penalty=repeat_penalty,
            think=think,
            base_url=settings.OLLAMA_URL,
            usage_context=usage_context,
            response_schema=response_schema,
        )
