"""Метрики качества разметки: подкатегории и адреса. Без LLM, только БД и кэш.

Подкатегории — покрытие и соответствие таксономии; адреса — покрытие
геокодингом и доля точек, попавших в город паблика (для паблика с известным
городом точка в другом муниципалитете почти всегда ошибка, если этот город не
назван в тексте). Считается на стороне сервера: нужен доступ к БД и к
``data/geo_cache.json``.
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime

from sqlalchemy import select

from backend.db.comment_analysis import CommentAnalysis
from backend.db.comments import Comment
from backend.db.posts import Post
from backend.db.public_social_links import PublicSocialLink
from backend.db.publications import Publication
from backend.db.publics import Public
from backend.modules.analytics.constants import COMPLAINT_MESSAGE_TYPES
from backend.modules.analytics.constants import SUBCATEGORY_ALIASES
from backend.modules.analytics.services.pain_map_service import PainMapService
from backend.modules.analytics.utils.case_extractor import is_valid_case_title
from backend.modules.analytics.utils.location_geocode_strategy import (
    LocationContext,
    locality_from_public,
)

APPEAL_TYPES = tuple(COMPLAINT_MESSAGE_TYPES) + ("request",)


def _pct(part: int, total: int) -> float:
    return round(part * 100 / total, 1) if total else 0.0


def _stem_match(left: str, right: str) -> bool:
    left, right = left.lower(), right.lower()
    return bool(left) and bool(right) and (left[:5] in right or right[:5] in left)


async def subcategory_report(session, since: datetime | None) -> dict:
    query = (
        select(CommentAnalysis.hierarchy, CommentAnalysis.message_type)
        .where(CommentAnalysis.hierarchy.isnot(None))
    )
    if since is not None:
        query = query.where(CommentAnalysis.created_at >= since)

    by_category: dict[str, Counter] = defaultdict(Counter)
    filled = off_taxonomy = total = 0

    for hierarchy, message_type in (await session.execute(query)).all():
        if str(message_type or "") not in APPEAL_TYPES:
            continue
        data = hierarchy if isinstance(hierarchy, dict) else json.loads(hierarchy or "{}")
        category = str((data or {}).get("category") or "").strip()
        subcategory = str((data or {}).get("subcategory") or "").strip()
        if not category:
            continue

        total += 1
        by_category[category][subcategory or "(пусто)"] += 1
        if subcategory:
            filled += 1
            allowed = SUBCATEGORY_ALIASES.get(category)
            if allowed is not None and subcategory not in allowed:
                off_taxonomy += 1

    categories = {}
    for category, counter in sorted(by_category.items(), key=lambda kv: -sum(kv[1].values())):
        count = sum(counter.values())
        empty = counter.get("(пусто)", 0)
        categories[category] = {
            "appeals": count,
            "with_subcategory_pct": _pct(count - empty, count),
            "top": counter.most_common(5),
        }

    return {
        "appeals": total,
        "with_subcategory_pct": _pct(filled, total),
        "off_taxonomy": off_taxonomy,
        "off_taxonomy_pct": _pct(off_taxonomy, filled),
        "categories": categories,
    }


async def address_report(session, since: datetime | None) -> dict:
    query = (
        select(
            CommentAnalysis.hierarchy,
            Comment.text,
            Public.name,
            Post.title,
        )
        .join(Comment, Comment.id == CommentAnalysis.comment_id)
        .join(Publication, Publication.id == Comment.publication_id)
        .join(Post, Post.id == Publication.post_id)
        .join(PublicSocialLink, PublicSocialLink.id == Publication.public_social_link_id)
        .join(Public, Public.id == PublicSocialLink.public_id)
        .where(CommentAnalysis.hierarchy.isnot(None))
    )
    if since is not None:
        query = query.where(CommentAnalysis.created_at >= since)

    map_service = PainMapService(session)
    cache = map_service.cache_snapshot()
    if not cache:
        return {"error": "geo-cache пуст: гео-метрики считаются там, где лежит data/geo_cache.json"}

    cases = geocoded = with_city = in_city = 0
    foreign: Counter = Counter()
    # Разрез по геокодеру: у каждой точки в кэше записано, кто её нашёл.
    by_source: dict[str, Counter] = defaultdict(Counter)

    for hierarchy, text, public_name, source_title in (await session.execute(query)).all():
        data = hierarchy if isinstance(hierarchy, dict) else json.loads(hierarchy or "{}")
        case_name = str((data or {}).get("case") or "").strip()
        if not case_name or not is_valid_case_title(case_name):
            continue

        cases += 1
        context = LocationContext(
            case_name=case_name,
            public_name=str(public_name or ""),
            source_title=str(source_title or ""),
            comment_text=str(text or ""),
        )
        geo = map_service.cached_geocode_for_context(context, cache)
        if not geo:
            continue
        geocoded += 1
        source = str(geo.get("source") or "?")
        by_source[source]["geocoded"] += 1

        city = locality_from_public(public_name, source_title)
        if not city:
            continue
        with_city += 1
        by_source[source]["checkable"] += 1
        point_place = " ".join(
            str(geo.get(key) or "") for key in ("municipality", "locality")
        )
        if _stem_match(city, point_place):
            in_city += 1
            by_source[source]["in_public_city"] += 1
        elif city.lower()[:5] not in str(text or "").lower():
            foreign[f"[{source}] {city} → {point_place.strip() or '?'}"] += 1
            by_source[source]["mismatched"] += 1

    return {
        "cases": cases,
        "geocoded": geocoded,
        "geocoded_pct": _pct(geocoded, cases),
        "checkable": with_city,
        "in_public_city": in_city,
        "in_public_city_pct": _pct(in_city, with_city),
        "top_mismatches": foreign.most_common(10),
        "by_source": {
            name: {
                "geocoded": counter["geocoded"],
                "checkable": counter["checkable"],
                "in_public_city": counter["in_public_city"],
                "mismatched": counter["mismatched"],
                "in_public_city_pct": _pct(counter["in_public_city"], counter["checkable"]),
            }
            for name, counter in sorted(by_source.items(), key=lambda kv: -kv[1]["geocoded"])
        },
    }




async def build_quality_report(session, since: datetime | None = None) -> dict:
    """Полный отчёт: подкатегории и адреса."""

    return {
        "subcategories": await subcategory_report(session, since),
        "addresses": await address_report(session, since),
    }
