"""Агрегаты по постам VK для отчёта.

Чистая функция: на вход — список словарей с метриками (то, что отдаёт
``post_repository`` или ``loaders/csv_loader``), на выходе — словарь
сводной статистики, который дальше уходит в charts и в LLM-промпт.

Без БД и без сетевых вызовов: вся работа над уже загруженными данными.
"""
from __future__ import annotations

from backend.modules.report.utils.datetime_parse import parse_vk_datetime
from backend.modules.report.utils.numeric import safe_int


def analyze_vk(posts: list[dict]) -> dict:
    """Сводная статистика по VK-постам + точки для графиков + топ-5."""

    if not posts:
        return {"error": "Нет данных по VK"}

    likes_all = [safe_int(p.get("likes")) for p in posts]
    views_all = [safe_int(p.get("views")) for p in posts]
    comments_all = [safe_int(p.get("comments")) for p in posts]

    points: list[dict] = []
    for p in posts:
        dt = parse_vk_datetime(p.get("date"))
        if dt is None:
            continue
        points.append({
            "dt": dt,
            "views": safe_int(p.get("views")),
            "likes": safe_int(p.get("likes")),
            "comments": safe_int(p.get("comments")),
        })
    points.sort(key=lambda x: x["dt"])

    top_by_likes = sorted(posts, key=lambda x: safe_int(x.get("likes")), reverse=True)[:5]
    top_by_views = sorted(posts, key=lambda x: safe_int(x.get("views")), reverse=True)[:5]

    # Считаем число подписчиков и название канала по списку source_key:
    # одна площадка — её цифры, несколько — суммируем подписчиков и
    # ставим «N площадки» в качестве названия канала.
    source_info: dict[str, dict] = {}
    for post in posts:
        source_key = str(post.get("source_key") or "")
        if not source_key:
            continue
        bucket = source_info.setdefault(
            source_key,
            {"group_members": 0, "channel": str(post.get("channel") or "").strip()},
        )
        bucket["group_members"] = max(
            int(bucket["group_members"] or 0),
            safe_int(post.get("group_members")),
        )
        if not bucket["channel"] and post.get("channel"):
            bucket["channel"] = str(post.get("channel")).strip()

    if len(source_info) == 1:
        only_source = next(iter(source_info.values()))
        group_members = int(only_source["group_members"] or 0)
        channel = str(only_source["channel"] or "").strip() or None
    elif source_info:
        group_members = sum(int(item["group_members"] or 0) for item in source_info.values())
        channel = f"{len(source_info)} площадки"
    else:
        group_members = safe_int(posts[0].get("group_members", 0))
        channel = str(posts[0].get("channel") or "").strip() or None

    return {
        "platform": "VK",
        "total_posts": len(posts),
        "avg_likes": round(sum(likes_all) / len(likes_all), 1) if likes_all else 0,
        "avg_views": round(sum(views_all) / len(views_all), 1) if views_all else 0,
        "avg_comments": round(sum(comments_all) / len(comments_all), 1) if comments_all else 0,
        "max_likes": max(likes_all) if likes_all else 0,
        "max_views": max(views_all) if views_all else 0,
        "max_comments": max(comments_all) if comments_all else 0,
        "group_members": group_members,
        "channel": channel,
        "top_by_likes": top_by_likes,
        "top_by_views": top_by_views,
        "points": points,
    }
