"""График по постам Дзена для вставки в PDF."""
from __future__ import annotations

import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from backend.modules.report.utils.numeric import safe_int


def create_dzen_charts(stats: dict, charts_dir: str = "charts") -> list[str]:
    """Сохраняет столбчатый «топ-5 постов по просмотрам» и возвращает пути."""

    os.makedirs(charts_dir, exist_ok=True)
    charts: list[str] = []

    if not stats.get("top_by_views"):
        return charts

    labels = [f"#{i+1}" for i in range(len(stats["top_by_views"]))]
    values = [safe_int(p.get("views")) for p in stats["top_by_views"]]
    plt.figure(figsize=(8, 4))
    plt.bar(labels, values, color="orange")
    plt.title("Топ-5 постов по просмотрам")
    plt.xlabel("Пост")
    plt.ylabel("Просмотры")
    plt.grid(True, alpha=0.3, axis="y")
    path = os.path.join(charts_dir, "dzen_top.png")
    plt.savefig(path, dpi=150, bbox_inches="tight")
    plt.close()
    charts.append(path)

    return charts
