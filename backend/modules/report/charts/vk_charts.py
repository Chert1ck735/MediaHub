"""Графики по постам VK для вставки в PDF.

Берёт stats от ``analyzers/vk_analyzer`` и рисует ОДИН компактный PNG:
просмотры/лайки/комментарии, агрегированные по неделям (бары) — без
ежедневного шума и одиночных выбросов, которые плющат дневные линии.
"""
from __future__ import annotations

import os
from collections import defaultdict
from datetime import timedelta

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


def _weekly(points: list[dict]) -> tuple[list, list[int], list[int], list[int]]:
    """Суммирует метрики по неделям (по понедельникам). Возвращает (даты, v, l, c)."""
    buckets: dict = defaultdict(lambda: [0, 0, 0])
    for p in points:
        dt = p["dt"]
        week_start = (dt - timedelta(days=dt.weekday())).date()
        b = buckets[week_start]
        b[0] += int(p.get("views", 0))
        b[1] += int(p.get("likes", 0))
        b[2] += int(p.get("comments", 0))
    weeks = sorted(buckets)
    views = [buckets[w][0] for w in weeks]
    likes = [buckets[w][1] for w in weeks]
    comments = [buckets[w][2] for w in weeks]
    return weeks, views, likes, comments


def create_vk_charts(stats: dict, charts_dir: str = "charts") -> list[str]:
    """Сохраняет один график (3 подграфика по неделям) и возвращает путь к нему."""

    os.makedirs(charts_dir, exist_ok=True)
    points = stats.get("points") or []
    if not points:
        return []

    weeks, views, likes, comments = _weekly(points)
    labels = [w.strftime("%d.%m") for w in weeks]
    series = [
        ("Просмотры за неделю", views, "#e6704d"),
        ("Лайки за неделю", likes, "#4caf50"),
        ("Комментарии за неделю", comments, "#6aa0d6"),
    ]

    fig, axes = plt.subplots(3, 1, figsize=(10, 8), sharex=True)
    for ax, (title, data, color) in zip(axes, series):
        ax.bar(range(len(data)), data, color=color, width=0.8)
        ax.set_title(title, fontsize=11)
        ax.grid(True, axis="y", alpha=0.3)
    axes[-1].set_xticks(range(len(labels)))
    axes[-1].set_xticklabels(labels, rotation=45, ha="right", fontsize=8)
    fig.tight_layout()

    path = os.path.join(charts_dir, "vk_weekly.png")
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return [path]
