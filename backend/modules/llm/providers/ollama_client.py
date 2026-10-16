from __future__ import annotations

import time
from typing import Any

import httpx

from backend.app.config import settings
from backend.modules.llm import usage_metrics
from backend.modules.llm.interfaces import BaseLLMClient, LLMError
from backend.modules.llm.prompt_loader import render_prompt
from backend.modules.llm.providers.logging import get_llm_provider_logger

logger = get_llm_provider_logger(__name__)


class QwenClient(BaseLLMClient):
    """Синхронный клиент Ollama, оставленный под историческим именем."""

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
        usage_context: str | None = None,
        response_schema: dict[str, Any] | None = None,
        **_: Any,
    ):
        # Ollama принимает JSON Schema в поле format и ограничивает генерацию по ней.
        self.response_schema = response_schema
        self.model = model or settings.OLLAMA_MODEL
        self.base_url = (base_url or settings.OLLAMA_URL).rstrip("/")
        self.timeout = timeout or settings.OLLAMA_TIMEOUT
        self.num_predict = num_predict
        self.usage_context = usage_context or "general"
        self.temperature = temperature
        self.top_p = top_p
        self.top_k = top_k
        self.repeat_penalty = repeat_penalty
        self.think = False
        self._timeout = httpx.Timeout(float(self.timeout))

    def _options(self) -> dict[str, Any]:
        options: dict[str, Any] = {
            "temperature": self.temperature,
            "top_p": self.top_p,
            "top_k": self.top_k,
            "repeat_penalty": self.repeat_penalty,
        }
        if self.num_predict is not None:
            options["num_predict"] = self.num_predict
        return options

    def _post(
        self,
        path: str,
        payload: dict[str, Any],
        *,
        operation: str,
    ) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        started_at = time.perf_counter()
        status_code: int | None = None
        gpu_monitor = usage_metrics.make_gpu_monitor()
        if gpu_monitor is not None:
            gpu_monitor.start()

        try:
            logger.info("Calling Ollama %s with model=%s", path, self.model)
            with httpx.Client(timeout=self._timeout, trust_env=False) as client:
                response = client.post(url, json=payload)
            status_code = response.status_code
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPStatusError as exc:
            body = exc.response.text[:1000]
            self._record_usage_event(
                path=path,
                operation=operation,
                started_at=started_at,
                status_code=exc.response.status_code,
                success=False,
                error=f"HTTP {exc.response.status_code}: {body}",
                gpu_monitor=gpu_monitor,
            )
            raise LLMError(
                f"Ollama request failed with HTTP {exc.response.status_code}: {body}"
            ) from exc
        except httpx.RequestError as exc:
            self._record_usage_event(
                path=path,
                operation=operation,
                started_at=started_at,
                status_code=status_code,
                success=False,
                error=str(exc),
                gpu_monitor=gpu_monitor,
            )
            raise LLMError(f"Ollama request failed: {exc}") from exc
        except ValueError as exc:
            self._record_usage_event(
                path=path,
                operation=operation,
                started_at=started_at,
                status_code=status_code,
                success=False,
                error=f"Invalid JSON: {exc}",
                gpu_monitor=gpu_monitor,
            )
            raise LLMError(f"Ollama returned invalid JSON: {exc}") from exc

        if not isinstance(data, dict):
            self._record_usage_event(
                path=path,
                operation=operation,
                started_at=started_at,
                status_code=status_code,
                success=False,
                error=f"Unexpected response: {data!r}",
                gpu_monitor=gpu_monitor,
            )
            raise LLMError(f"Ollama returned unexpected response: {data!r}")

        self._record_usage_event(
            path=path,
            operation=operation,
            started_at=started_at,
            status_code=status_code,
            success=True,
            error=None,
            gpu_monitor=gpu_monitor,
            data=data,
        )
        return data

    def _record_usage_event(
        self,
        *,
        path: str,
        operation: str,
        started_at: float,
        status_code: int | None,
        success: bool,
        error: str | None,
        gpu_monitor: usage_metrics.GpuUsageMonitor | None,
        data: dict[str, Any] | None = None,
    ) -> None:
        if gpu_monitor is not None:
            gpu_monitor.stop()

        usage_metrics.record_llm_usage(
            {
                "provider": "ollama",
                "base_url": self.base_url,
                "model": self.model,
                "endpoint": path,
                "operation": operation,
                "usage_context": self.usage_context,
                "success": success,
                "error": error,
                "http_status_code": status_code,
                "duration_seconds": round(time.perf_counter() - started_at, 4),
                "response_chars": usage_metrics.response_text_length(data or {}),
                "options": self._options(),
                "gpu": gpu_monitor.snapshot() if gpu_monitor is not None else None,
                **usage_metrics.extract_ollama_metrics(data or {}),
            }
        )

    @staticmethod
    def _messages_to_prompt(messages: list[dict]) -> str:
        lines: list[str] = []
        for msg in messages:
            role = str(msg.get("role", "user")).upper()
            content = str(msg.get("content", "")).strip()
            if not content:
                continue
            lines.append(
                render_prompt(
                    "client/message_prompt_part.md",
                    role=role,
                    content=content,
                )
            )
        return "\n\n".join(lines)

    def _with_common_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self.think is not None:
            payload["think"] = self.think
        if self.response_schema is not None:
            payload["format"] = self.response_schema
        keep_alive = getattr(settings, "OLLAMA_KEEP_ALIVE", None)
        if keep_alive:
            payload["keep_alive"] = keep_alive
        return payload

    def _call_chat(self, messages: list[dict]) -> str:
        data = self._post(
            "/api/chat",
            self._with_common_payload(
                {
                    "model": self.model,
                    "stream": False,
                    "messages": messages,
                    "options": self._options(),
                }
            ),
            operation="chat",
        )
        message = data.get("message")
        if not isinstance(message, dict):
            raise LLMError(f"Ollama chat response has no message: {data!r}")
        content = message.get("content")
        if not isinstance(content, str):
            raise LLMError(f"Ollama chat response has no content: {data!r}")
        return content.strip()

    def _call_generate(self, messages: list[dict]) -> str:
        data = self._post(
            "/api/generate",
            self._with_common_payload(
                {
                    "model": self.model,
                    "stream": False,
                    "prompt": self._messages_to_prompt(messages),
                    "options": self._options(),
                }
            ),
            operation="generate",
        )
        content = data.get("response")
        if not isinstance(content, str):
            raise LLMError(f"Ollama generate response has no content: {data!r}")
        return content.strip()

    def generate(self, messages: list[dict]) -> str:
        return self._call_chat(messages)

    def count_tokens(self, text: str) -> int:
        options = self._options()
        options["num_predict"] = 1
        data = self._post(
            "/api/generate",
            {
                "model": self.model,
                "stream": False,
                "raw": True,
                "prompt": text,
                "options": options,
            },
            operation="count_tokens",
        )
        value = data.get("prompt_eval_count")
        if isinstance(value, int):
            return value
        raise LLMError(f"Ollama response has no prompt_eval_count: {data!r}")
