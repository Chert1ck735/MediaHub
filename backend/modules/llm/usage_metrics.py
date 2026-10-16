from __future__ import annotations

import json
import shutil
import subprocess
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from backend.app.config import settings

_WRITE_LOCK = threading.Lock()


def _utc_now() -> datetime:
    """Возвращает текущую дату и время с часовым поясом в формате всемирного времени."""

    return datetime.now(timezone.utc)


def _iso_now() -> str:
    """Возвращает текущее всемирное время в стандартном строковом формате."""

    return _utc_now().isoformat()


def _duration_ms(value: Any) -> float | None:
    """Переводит длительности Оллама из наносекунд в миллисекунды."""

    if isinstance(value, (int, float)):
        return round(float(value) / 1_000_000, 3)
    return None


def _safe_int(value: Any) -> int | None:
    """Преобразует значение в целое число или возвращает пустое значение при ошибке."""

    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    """Читает валидные структурированные объекты из файла журнала метрик."""

    if not path.exists():
        return []

    events: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as file:
        for line in file:
            raw = line.strip()
            if not raw:
                continue
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                events.append(payload)
    return events


def _parse_timestamp(value: Any) -> datetime | None:
    """Разбирает временную метку в формате ИСО из события метрик."""

    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _mean(values: list[float | int]) -> float | None:
    """Возвращает округленное среднее или пустое значение для пустой коллекции."""

    if not values:
        return None
    return round(sum(float(value) for value in values) / len(values), 4)


class GpuUsageMonitor:
    """Собирает показания системной утилиты видеокарты во время запроса к языковой модели."""

    def __init__(self, interval_seconds: float | None = None) -> None:
        """Инициализирует состояние мониторинга видеокарты и ищет системную утилиту."""

        self.interval_seconds = max(interval_seconds or settings.LLM_GPU_METRICS_INTERVAL, 0.2)
        self.command = shutil.which("nvidia-smi")
        self.available = bool(self.command)
        self.error: str | None = None
        self.samples_collected = 0
        self.peak_utilization_percent: int | None = None
        self.peak_memory_used_mb: int | None = None
        self.peak_memory_total_mb: int | None = None
        self.peak_temperature_c: int | None = None
        self.peak_device_index: int | None = None
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Запускает фоновый сбор метрик видеокарты, если доступна системная утилита."""

        if not self.available:
            return
        self._sample_once()
        self._thread = threading.Thread(
            target=self._run,
            name="llm-gpu-usage-monitor",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        """Останавливает фоновый сбор и недолго ждет завершения потока."""

        if not self._thread:
            return
        self._stop_event.set()
        self._thread.join(timeout=self.interval_seconds * 3)

    def snapshot(self) -> dict[str, Any]:
        """Возвращает собранные пиковые метрики видеокарты как сериализуемый словарь."""

        memory_utilization = None
        if self.peak_memory_used_mb is not None and self.peak_memory_total_mb:
            memory_utilization = round(
                self.peak_memory_used_mb / self.peak_memory_total_mb * 100,
                2,
            )
        return {
            "monitoring_available": self.available,
            "sample_interval_seconds": self.interval_seconds,
            "samples_collected": self.samples_collected,
            "peak_utilization_percent": self.peak_utilization_percent,
            "peak_memory_used_mb": self.peak_memory_used_mb,
            "peak_memory_total_mb": self.peak_memory_total_mb,
            "peak_memory_utilization_percent": memory_utilization,
            "peak_temperature_c": self.peak_temperature_c,
            "peak_device_index": self.peak_device_index,
            "error": self.error,
        }

    def _run(self) -> None:
        """Непрерывно собирает замеры до сигнала остановки."""

        while not self._stop_event.wait(self.interval_seconds):
            self._sample_once()

    def _sample_once(self) -> None:
        """Выполняет один замер системной утилиты и обрабатывает вывод."""

        if not self.command:
            return
        try:
            result = subprocess.run(
                [
                    self.command,
                    "--query-gpu=index,utilization.gpu,memory.used,memory.total,temperature.gpu",
                    "--format=csv,noheader,nounits",
                ],
                capture_output=True,
                text=True,
                check=False,
                timeout=5,
            )
            if result.returncode != 0:
                self.error = (result.stderr or result.stdout or "nvidia-smi failed").strip()
                return
            self._consume_output(result.stdout)
        except Exception as exc:
            self.error = str(exc)

    def _consume_output(self, output: str) -> None:
        """Разбирает табличный вывод системной утилиты и обновляет пиковые счетчики."""

        for raw_line in output.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            parts = [part.strip() for part in line.split(",")]
            if len(parts) < 5:
                continue
            try:
                device_index = int(parts[0])
                utilization = int(parts[1])
                memory_used = int(parts[2])
                memory_total = int(parts[3])
                temperature = int(parts[4])
            except ValueError:
                continue

            self.samples_collected += 1
            if self.peak_utilization_percent is None or utilization >= self.peak_utilization_percent:
                self.peak_utilization_percent = utilization
                self.peak_device_index = device_index
                self.peak_memory_used_mb = memory_used
                self.peak_memory_total_mb = memory_total
                self.peak_temperature_c = temperature
            elif self.peak_memory_used_mb is None or memory_used > self.peak_memory_used_mb:
                self.peak_memory_used_mb = memory_used
                self.peak_memory_total_mb = memory_total


def make_gpu_monitor() -> GpuUsageMonitor | None:
    """Создает монитор видеокарты, если включены метрики использования и видеокарты."""

    if not settings.LLM_USAGE_METRICS_ENABLED or not settings.LLM_GPU_METRICS_ENABLED:
        return None
    return GpuUsageMonitor()


def extract_ollama_metrics(data: dict[str, Any]) -> dict[str, Any]:
    """Извлекает метрики токенов и длительности из тела ответа Оллама."""

    prompt_tokens = _safe_int(data.get("prompt_eval_count"))
    completion_tokens = _safe_int(data.get("eval_count"))
    total_tokens = None
    if prompt_tokens is not None or completion_tokens is not None:
        total_tokens = (prompt_tokens or 0) + (completion_tokens or 0)

    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "total_duration_ms": _duration_ms(data.get("total_duration")),
        "load_duration_ms": _duration_ms(data.get("load_duration")),
        "prompt_eval_duration_ms": _duration_ms(data.get("prompt_eval_duration")),
        "eval_duration_ms": _duration_ms(data.get("eval_duration")),
    }


def response_text_length(data: dict[str, Any]) -> int | None:
    """Возвращает длину текста ответа для тела чата или генерации Оллама."""

    response = data.get("response")
    if isinstance(response, str):
        return len(response)

    message = data.get("message")
    if isinstance(message, dict):
        content = message.get("content")
        if isinstance(content, str):
            return len(content)

    return None


def record_llm_usage(event: dict[str, Any]) -> None:
    """Дописывает одно событие использования языковой модели в настроенный файл журнала."""

    if not settings.LLM_USAGE_METRICS_ENABLED:
        return

    path = settings.llm_usage_metrics_file_abs
    payload = {
        "id": str(uuid.uuid4()),
        "timestamp": _iso_now(),
        **event,
    }

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        with _WRITE_LOCK:
            with path.open("a", encoding="utf-8") as file:
                file.write(line + "\n")
    except OSError:
        return


def build_usage_report(limit: int = 50, since_hours: int = 24) -> dict[str, Any]:
    """Агрегирует недавние события языковой модели в метрики для панели."""

    path = settings.llm_usage_metrics_file_abs
    events = _read_jsonl(path)
    cutoff = _utc_now() - timedelta(hours=max(since_hours, 1))

    filtered: list[dict[str, Any]] = []
    for event in events:
        timestamp = _parse_timestamp(event.get("timestamp"))
        if timestamp is None or timestamp >= cutoff:
            filtered.append(event)

    latest = filtered[-max(limit, 1) :]
    successful = [event for event in filtered if event.get("success") is True]
    failed = [event for event in filtered if event.get("success") is False]

    durations = [
        value
        for event in filtered
        if isinstance((value := event.get("duration_seconds")), (int, float))
    ]
    prompt_tokens = [
        value
        for event in filtered
        if isinstance((value := event.get("prompt_tokens")), int)
    ]
    completion_tokens = [
        value
        for event in filtered
        if isinstance((value := event.get("completion_tokens")), int)
    ]
    total_tokens = [
        value
        for event in filtered
        if isinstance((value := event.get("total_tokens")), int)
    ]

    gpu_snapshots = [
        event.get("gpu")
        for event in filtered
        if isinstance(event.get("gpu"), dict)
    ]

    by_operation: dict[str, dict[str, Any]] = {}
    by_context: dict[str, dict[str, Any]] = {}
    for event in filtered:
        operation = str(event.get("operation") or event.get("endpoint") or "unknown")
        usage_context = str(event.get("usage_context") or "general")
        _add_summary_bucket(by_operation, operation, event)
        _add_summary_bucket(by_context, usage_context, event)

    for bucket in [*by_operation.values(), *by_context.values()]:
        bucket["average_duration_seconds"] = _mean(bucket.pop("_durations"))

    return {
        "enabled": settings.LLM_USAGE_METRICS_ENABLED,
        "metrics_file": str(path),
        "since_hours": since_hours,
        "total_requests": len(filtered),
        "successful_requests": len(successful),
        "failed_requests": len(failed),
        "average_duration_seconds": _mean(durations),
        "total_prompt_tokens": sum(prompt_tokens),
        "total_completion_tokens": sum(completion_tokens),
        "total_tokens": sum(total_tokens),
        "average_tokens_per_request": _mean(total_tokens),
        "gpu": {
            "monitoring_enabled": settings.LLM_GPU_METRICS_ENABLED,
            "monitoring_available": any(
                snapshot.get("monitoring_available") for snapshot in gpu_snapshots
            ),
            "peak_utilization_percent": max(
                (
                    value
                    for snapshot in gpu_snapshots
                    if isinstance((value := snapshot.get("peak_utilization_percent")), int)
                ),
                default=None,
            ),
            "peak_memory_used_mb": max(
                (
                    value
                    for snapshot in gpu_snapshots
                    if isinstance((value := snapshot.get("peak_memory_used_mb")), int)
                ),
                default=None,
            ),
            "peak_temperature_c": max(
                (
                    value
                    for snapshot in gpu_snapshots
                    if isinstance((value := snapshot.get("peak_temperature_c")), int)
                ),
                default=None,
            ),
        },
        "by_operation": by_operation,
        "by_context": by_context,
        "latest_events": latest,
    }


def _add_summary_bucket(
    target: dict[str, dict[str, Any]],
    key: str,
    event: dict[str, Any],
) -> None:
    """Накапливает счетчики запросов и длительности в именованной группе."""

    bucket = target.setdefault(
        key,
        {
            "requests": 0,
            "failed_requests": 0,
            "average_duration_seconds": None,
            "_durations": [],
        },
    )
    bucket["requests"] += 1
    if event.get("success") is False:
        bucket["failed_requests"] += 1
    if isinstance(event.get("duration_seconds"), (int, float)):
        bucket["_durations"].append(event["duration_seconds"])
