from typing import Any

from backend.modules.llm.usage_metrics import build_usage_report


class FileUsageMetricsRepository:
    """Читает сводные метрики расхода LLM из локального журнала."""

    def build_report(self, *, limit: int, since_hours: int) -> dict[str, Any]:
        return build_usage_report(limit=limit, since_hours=since_hours)
