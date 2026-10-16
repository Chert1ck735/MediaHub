"""Нормализация категорий/подкатегорий в comment_analysis без LLM и пересборки.

Прогоняет существующую разметку через тот же нормализатор, что и классификатор:
чужая подкатегория перевешивается в свою категорию, свободные строки LLM
убираются. Дешёвая замена полной пересборке — только SQL и словарные правила,
ни одного запроса к модели.

Запуск:  python -m tools.normalize_hierarchy [--dry-run]
"""
from __future__ import annotations

import argparse
import asyncio

from sqlalchemy import select

from backend.db.comment_analysis import CommentAnalysis
from backend.db.comments import Comment
from backend.db.database import async_session_maker
from backend.modules.analytics.constants import COMPLAINT_MESSAGE_TYPES
from backend.modules.analytics.utils.category_classifier import normalize_hierarchy_values

# Правим только размеченные обращения. У gratitude/offtopic/irrelevant иерархия
# пустая намеренно — навязывать им категорию по тексту нельзя.
APPEAL_TYPES = tuple(COMPLAINT_MESSAGE_TYPES) + ("request",)

BATCH = 1000


async def run(dry_run: bool) -> None:
    checked = changed = 0
    async with async_session_maker() as session:
        last_id = None
        while True:
            query = (
                select(CommentAnalysis, Comment.text)
                .join(Comment, Comment.id == CommentAnalysis.comment_id)
                .where(CommentAnalysis.hierarchy.isnot(None))
                .order_by(CommentAnalysis.id)
                .limit(BATCH)
            )
            if last_id is not None:
                query = query.where(CommentAnalysis.id > last_id)
            rows = (await session.execute(query)).all()
            if not rows:
                break

            for analysis, text in rows:
                last_id = analysis.id
                hierarchy = dict(analysis.hierarchy or {})
                if str(analysis.message_type or "") not in APPEAL_TYPES:
                    continue
                if not str(hierarchy.get("category") or "").strip():
                    continue
                checked += 1
                category, subcategory, case_name = normalize_hierarchy_values(
                    category=str(hierarchy.get("category", "") or "").strip(),
                    subcategory=str(hierarchy.get("subcategory", "") or "").strip(),
                    case_name=str(hierarchy.get("case", "") or "").strip(),
                    source_text=str(text or ""),
                )
                normalized = {"category": category, "subcategory": subcategory, "case": case_name}
                if normalized != {
                    "category": hierarchy.get("category", ""),
                    "subcategory": hierarchy.get("subcategory", ""),
                    "case": hierarchy.get("case", ""),
                }:
                    changed += 1
                    if not dry_run:
                        analysis.hierarchy = normalized

            if not dry_run:
                await session.commit()

    mode = "проверено (dry-run)" if dry_run else "обновлено"
    print(f"записей: {checked}, {mode}: {changed}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="только посчитать, не писать")
    args = parser.parse_args()
    asyncio.run(run(args.dry_run))


if __name__ == "__main__":
    main()
