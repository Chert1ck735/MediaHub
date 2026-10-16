from __future__ import annotations

import time
from typing import Any

import httpx
from openai import OpenAI

from backend.app.config import settings
from backend.modules.llm import usage_metrics
from backend.modules.llm.interfaces import BaseLLMClient, LLMError
from backend.modules.llm.providers.logging import get_llm_provider_logger

logger = get_llm_provider_logger(__name__)

# Признаки того, что сервер не поддерживает response_format/json_schema.
_UNSUPPORTED_SCHEMA_MARKERS = (
    "response_format",
    "json_schema",
    "unsupported",
    "unrecognized",
    "not supported",
    "extra inputs are not permitted",
)


def _looks_like_unsupported_schema(exc: Exception) -> bool:
    message = str(exc).lower()
    return any(marker in message for marker in _UNSUPPORTED_SCHEMA_MARKERS)


class OpenAICompatibleClient(BaseLLMClient):
    """Клиент chat completions для серверов формата llama.cpp."""

    def __init__(
        self,
        model: str | None = None,
        timeout: int | None = None,
        num_predict: int | None = None,
        *,
        temperature: float = 0.6,
        top_p: float = 0.9,
        top_k: int = 40,
        repeat_penalty: float = 1.1,
        think: bool | None = False,
        base_url: str | None = None,
        api_key: str | None = None,
        usage_context: str | None = None,
        response_schema: dict[str, Any] | None = None,
        response_schema_name: str = "response",
        **_: Any,
    ):
        self.response_schema = response_schema
        self.response_schema_name = response_schema_name
        # Не все OpenAI-совместимые серверы понимают json_schema. Если сервер его
        # отвергнет, повторяем запрос без него и больше не пытаемся до перезапуска.
        self._structured_output_supported = True
        self.model = model or settings.OPENAI_COMPATIBLE_MODEL
        self.base_url = (base_url or settings.OPENAI_COMPATIBLE_BASE_URL).rstrip("/")
        self.api_key = api_key or settings.OPENAI_COMPATIBLE_API_KEY
        self.timeout = timeout or settings.OPENAI_COMPATIBLE_TIMEOUT
        self.num_predict = num_predict
        self.usage_context = usage_context or "general"
        self.temperature = temperature
        self.top_p = top_p
        self.top_k = top_k
        self.repeat_penalty = repeat_penalty
        self.think = False
        self.client = OpenAI(
            base_url=self.base_url,
            api_key=self.api_key,
            timeout=httpx.Timeout(
                connect=10.0,
                read=float(self.timeout),
                write=10.0,
                pool=10.0,
            ),
        )

    def _options(self) -> dict[str, Any]:
        options: dict[str, Any] = {
            "temperature": self.temperature,
            "top_p": self.top_p,
            "top_k": self.top_k,
            "repeat_penalty": self.repeat_penalty,
        }
        if self.num_predict is not None and self.num_predict > 0:
            options["max_tokens"] = self.num_predict
        return options

    def generate(self, messages: list[dict]) -> str:
        started_at = time.perf_counter()
        gpu_monitor = usage_metrics.make_gpu_monitor()
        if gpu_monitor is not None:
            gpu_monitor.start()

        try:
            logger.info(
                "Calling OpenAI-compatible chat completions with model=%s base_url=%s",
                self.model,
                self.base_url,
            )
            request_kwargs: dict[str, Any] = {
                "model": self.model,
                "messages": messages,
                "temperature": self.temperature,
                "top_p": self.top_p,
                "stream": False,
                "extra_body": {
                    "chat_template_kwargs": {
                        "enable_thinking": self.think,
                    },
                },
            }
            if self.num_predict is not None and self.num_predict > 0:
                request_kwargs["max_tokens"] = self.num_predict
            use_schema = self.response_schema is not None and self._structured_output_supported
            if use_schema:
                request_kwargs["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {
                        "name": self.response_schema_name,
                        "schema": self.response_schema,
                        "strict": True,
                    },
                }
            try:
                response = self.client.chat.completions.create(**request_kwargs)
            except Exception as exc:
                if not use_schema or not _looks_like_unsupported_schema(exc):
                    raise
                # Сервер не умеет constrained decoding — не теряем комментарий,
                # откатываемся на свободную генерацию (её и парсили раньше).
                logger.warning(
                    "Server rejected response_format=json_schema (%s); "
                    "falling back to unconstrained generation",
                    exc,
                )
                self._structured_output_supported = False
                request_kwargs.pop("response_format", None)
                response = self.client.chat.completions.create(**request_kwargs)
            content = response.choices[0].message.content
            if not isinstance(content, str) or not content.strip():
                raise LLMError(f"OpenAI-compatible response has no content: {response!r}")
            text = content.strip()
            self._record_usage_event(
                started_at=started_at,
                success=True,
                error=None,
                gpu_monitor=gpu_monitor,
                response_text=text,
                usage=getattr(response, "usage", None),
            )
            return text
        except LLMError:
            self._record_usage_event(
                started_at=started_at,
                success=False,
                error="empty content",
                gpu_monitor=gpu_monitor,
            )
            raise
        except Exception as exc:
            self._record_usage_event(
                started_at=started_at,
                success=False,
                error=str(exc),
                gpu_monitor=gpu_monitor,
            )
            raise LLMError(f"OpenAI-compatible request failed: {exc}") from exc

    def _record_usage_event(
        self,
        *,
        started_at: float,
        success: bool,
        error: str | None,
        gpu_monitor: usage_metrics.GpuUsageMonitor | None,
        response_text: str = "",
        usage: Any | None = None,
    ) -> None:
        if gpu_monitor is not None:
            gpu_monitor.stop()

        prompt_tokens = getattr(usage, "prompt_tokens", None)
        completion_tokens = getattr(usage, "completion_tokens", None)
        total_tokens = getattr(usage, "total_tokens", None)
        usage_metrics.record_llm_usage(
            {
                "provider": "openai_compatible",
                "base_url": self.base_url,
                "model": self.model,
                "endpoint": "/chat/completions",
                "operation": "chat",
                "usage_context": self.usage_context,
                "success": success,
                "error": error,
                "http_status_code": None,
                "duration_seconds": round(time.perf_counter() - started_at, 4),
                "response_chars": len(response_text),
                "prompt_eval_count": prompt_tokens,
                "eval_count": completion_tokens,
                "total_token_count": total_tokens,
                "options": self._options(),
                "gpu": gpu_monitor.snapshot() if gpu_monitor is not None else None,
            }
        )

    def count_tokens(self, text: str) -> int:
        # OpenAI-compatible llama.cpp servers do not expose a portable token count
        # endpoint. This heuristic is only a fallback for the optional interface.
        return max(1, len(text) // 4)

    def close(self) -> None:
        self.client.close()
