"""Точка входа модуля отчётов для роутера.

Сборку ведёт ``ReportOrchestrator``; здесь только состав зависимостей.
"""
from __future__ import annotations

from backend.modules.report.analyzers.dzen_analyzer import analyze_dzen
from backend.modules.report.analyzers.vk_analyzer import analyze_vk
from backend.modules.report.charts.dzen_charts import create_dzen_charts
from backend.modules.report.charts.vk_charts import create_vk_charts
from backend.modules.report.errors import ReportError  # noqa: F401  — роутер ловит его как service.ReportError
from backend.modules.report.loaders.csv_loader import load_dzen_data, load_vk_data
from backend.modules.report.services.llm_recommendations_service import generate_recommendations
from backend.modules.report.services.pdf_builder import generate_pdf
from backend.modules.report.services.report_orchestrator import (
    ReportOrchestrator,
    ReportOrchestratorDependencies,
)


def generate_report(
    platform: str,
    csv_path: str | None = None,
    output_path: str | None = None,
) -> str:
    orchestrator = ReportOrchestrator(
        ReportOrchestratorDependencies(
            load_vk_data=load_vk_data,
            load_dzen_data=load_dzen_data,
            analyze_vk=analyze_vk,
            analyze_dzen=analyze_dzen,
            create_vk_charts=create_vk_charts,
            create_dzen_charts=create_dzen_charts,
            generate_recommendations=generate_recommendations,
            generate_pdf=generate_pdf,
        )
    )
    return orchestrator.generate_report(platform, csv_path=csv_path, output_path=output_path)
