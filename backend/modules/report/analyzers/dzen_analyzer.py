"""Агрегаты по постам Дзена для отчёта.

В Дзене нет лайков/репостов как в VK — основная метрика views и время
прочтения. Возвращаем сводку и топ-5 по просмотрам.
"""
from __future__ import annotations

from backend.modules.report.utils.numeric import safe_int


def analyze_dzen(posts: list[dict]) -> dict:
    """Сводная статистика по постам Дзена + топ-5 по просмотрам."""

    if not posts:
        return {"error": "Нет данных по Дзену"}

    views = [safe_int(p.get("views")) for p in posts]
    read_times = [safe_int(p.get("time_to_read_sec")) for p in posts]

    top_by_views = sorted(posts, key=lambda x: safe_int(x.get("views")), reverse=True)[:5]
    channel = posts[0].get("channel", "") if posts else ""

    return {
        "platform": "Дзен",
        "channel": channel,
        "total_posts": len(posts),
        "avg_views": round(sum(views) / len(views), 1) if views else 0,
        "max_views": max(views) if views else 0,
        "avg_read_time_sec": round(sum(read_times) / len(read_times), 1) if read_times else 0,
        "top_by_views": top_by_views,
    }
