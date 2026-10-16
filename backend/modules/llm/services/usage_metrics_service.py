from typing import Any

from backend.modules.llm.interfaces import UsageMetricsReader
from backend.modules.llm.repositories.usage_metrics_repository import (
    FileUsageMetricsRepository,
)


class LLMUsageMetricsService:
    """Строит отчёты о расходе LLM через переданный источник метрик."""

    def __init__(
        self,
        metrics_reader: UsageMetricsReader | None = None,
    ):
        self.metrics_reader = metrics_reader or FileUsageMetricsRepository()

    def build_report(self, *, limit: int, since_hours: int) -> dict[str, Any]:
        return self.metrics_reader.build_report(limit=limit, since_hours=since_hours)
