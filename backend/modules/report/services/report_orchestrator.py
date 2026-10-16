from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from backend.app.config import settings
from backend.modules.report.analyzers.dzen_analyzer import analyze_dzen
from backend.modules.report.analyzers.vk_analyzer import analyze_vk
from backend.modules.report.charts.dzen_charts import create_dzen_charts
from backend.modules.report.charts.vk_charts import create_vk_charts
from backend.modules.report.errors import ReportError
from backend.modules.report.loaders.csv_loader import load_dzen_data, load_vk_data
from backend.modules.report.services.llm_recommendations_service import generate_recommendations
from backend.modules.report.services.pdf_builder import generate_pdf

_CHARTS_DIR = "charts"


@dataclass(frozen=True)
class ReportOrchestratorDependencies:
    load_vk_data: Callable[[str], list[dict]] = load_vk_data
    load_dzen_data: Callable[[str], list[dict]] = load_dzen_data
    analyze_vk: Callable[[list[dict]], dict] = analyze_vk
    analyze_dzen: Callable[[list[dict]], dict] = analyze_dzen
    create_vk_charts: Callable[[dict, str], list[str]] = create_vk_charts
    create_dzen_charts: Callable[[dict, str], list[str]] = create_dzen_charts
    generate_recommendations: Callable[[str, dict], str] = generate_recommendations
    generate_pdf: Callable[..., str] = generate_pdf
    vk_default_csv_path: str = str(settings.vk_parser_output_abs)
    dzen_default_csv_path: str = "dzen_posts.csv"
    charts_dir: str = _CHARTS_DIR


class ReportOrchestrator:
    """Ведёт сборку отчёта, не завися ни от HTTP, ни от модулей-фасадов."""

    def __init__(self, deps: ReportOrchestratorDependencies | None = None) -> None:
        self._deps = deps or ReportOrchestratorDependencies()

    def generate_report(
        self,
        platform: str,
        csv_path: str | None = None,
        output_path: str | None = None,
    ) -> str:
        stats, charts, default_output = self._build_from_csv(platform, csv_path)
        recommendations = self._deps.generate_recommendations(stats.get("platform", platform), stats)
        out = output_path or default_output
        self._deps.generate_pdf(stats.get("platform", platform), stats, charts, recommendations, out)
        return out

    def generate_report_from_posts(
        self,
        platform: str,
        posts: list[dict],
        output_path: str | None = None,
        pains_data: dict | None = None,
    ) -> str:
        stats, charts, default_output = self._build_from_posts(platform, posts)
        recommendations = self._deps.generate_recommendations(stats.get("platform", platform), stats)
        out = output_path or default_output
        self._deps.generate_pdf(
            stats.get("platform", platform),
            stats,
            charts,
            recommendations,
            out,
            pains_data=pains_data,
        )
        return out

    def _build_from_csv(self, platform: str, csv_path: str | None) -> tuple[dict, list[str], str]:
        normalized = platform.lower()
        if normalized == "vk":
            posts = self._deps.load_vk_data(csv_path or self._deps.vk_default_csv_path)
            if not posts:
                raise ReportError("Нет данных по VK")
            return self._build_vk(posts)
        if normalized in ("dzen", "дзен"):
            posts = self._deps.load_dzen_data(csv_path or self._deps.dzen_default_csv_path)
            if not posts:
                raise ReportError("Нет данных по Дзену")
            return self._build_dzen(posts)
        raise ReportError(f"Неизвестная площадка: {platform}. Допустимые: vk, dzen")

    def _build_from_posts(self, platform: str, posts: list[dict]) -> tuple[dict, list[str], str]:
        normalized = platform.lower()
        if normalized == "vk":
            if not posts:
                raise ReportError("Нет данных по VK в базе")
            return self._build_vk(posts)
        if normalized in ("dzen", "дзен"):
            if not posts:
                raise ReportError("Нет данных по Дзену")
            return self._build_dzen(posts)
        raise ReportError(f"Неизвестная площадка: {platform}. Допустимые: vk, dzen")

    def _build_vk(self, posts: list[dict]) -> tuple[dict, list[str], str]:
        stats = self._deps.analyze_vk(posts)
        charts = self._deps.create_vk_charts(stats, self._deps.charts_dir)
        return stats, charts, "report_vk.pdf"

    def _build_dzen(self, posts: list[dict]) -> tuple[dict, list[str], str]:
        stats = self._deps.analyze_dzen(posts)
        charts = self._deps.create_dzen_charts(stats, self._deps.charts_dir)
        return stats, charts, "report_dzen.pdf"


def generate_report(
    platform: str,
    csv_path: str | None = None,
    output_path: str | None = None,
) -> str:
    return ReportOrchestrator().generate_report(
        platform,
        csv_path=csv_path,
        output_path=output_path,
    )


def generate_report_from_posts(
    platform: str,
    posts: list[dict],
    output_path: str | None = None,
    pains_data: dict | None = None,
) -> str:
    return ReportOrchestrator().generate_report_from_posts(
        platform,
        posts,
        output_path=output_path,
        pains_data=pains_data,
    )
