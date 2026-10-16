import asyncio
import csv
import sys
from pathlib import Path

from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db import CommentAnalysis, Comment, Publication, Public, PublicSocialLink
from backend.db.database import async_session_maker

if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

OUTPUT = Path("data/classification_dataset.csv")
LIMIT = 50
ONLY_WITH_ANALYSIS = True

CSV_COLUMNS = [
    "comment_id",
    "comment",

    # Ручная разметка / ground truth
    "true_relevance",
    "true_sentiment",
    "true_message_type",
    "true_category",
    "true_subcategory",
    "true_case",

    # Текущие значения модели из БД, если есть
    "predicted_relevance",
    "predicted_sentiment",
    "predicted_message_type",
    "predicted_category",
    "predicted_subcategory",
    "predicted_case",

    # Служебные поля
    "classification_source",
    "classification_state",
]


def enum_value(value) -> str:
    if value is None:
        return ""
    return str(getattr(value, "value", value) or "")


def hierarchy_value(analysis: CommentAnalysis | None, key: str) -> str:
    if analysis is None:
        return ""
    hierarchy = getattr(analysis, "hierarchy", None)
    if not isinstance(hierarchy, dict):
        return ""
    return str(hierarchy.get(key) or "")

async def load_rows(
        db: AsyncSession,
        *,
        limit: int,
        only_with_analysis: bool,
        with_subcategories: bool = False
) -> list[dict[str, str]]:
    base_query = (
        select(Comment, CommentAnalysis)
        .select_from(Comment)
        .join(
            Publication,
            Publication.id == Comment.publication_id,
        )
        .join(
            PublicSocialLink,
            PublicSocialLink.id == Publication.public_social_link_id,
        )
        .join(
            Public,
            Public.id == PublicSocialLink.public_id,
        )
        .join(
            CommentAnalysis,
            CommentAnalysis.comment_id == Comment.id,
        )
        .where(Comment.is_deleted.is_(False))
        .where(Comment.text.is_not(None))
        .order_by(Comment.created_at.asc())
    )

    relevant_query = (
        base_query
        .where(CommentAnalysis.hierarchy.is_not(None))
        .where(CommentAnalysis.hierarchy["category"].as_string() != "")
        .limit(limit)
    )

    irrelevant_query = (
        base_query
        .where(
            or_(
                CommentAnalysis.hierarchy.is_(None),
                CommentAnalysis.hierarchy["category"].as_string() == "",
            )
        )
        .limit(50)
    )

    relevant = (await db.execute(relevant_query)).all()
    irrelevant = (await db.execute(irrelevant_query)).all()

    result_rows = relevant + irrelevant

    rows = []

    seen_texts: set[str] = set()

    for comment, analysis in result_rows:
        text = (comment.text or "").strip()
        if not text:
            continue

        # простая дедупликация одинаковых комментариев
        normalized = " ".join(text.lower().split())
        if normalized in seen_texts:
            continue
        seen_texts.add(normalized)

        rows.append(
            {
                "comment_id": str(comment.id),
                "comment": text,

                "true_relevance": enum_value(getattr(analysis, "relevance", None)),
                "true_sentiment": enum_value(getattr(analysis, "sentiment", None)),
                "true_message_type": str(getattr(analysis, "message_type", "") or ""),
                "true_category": hierarchy_value(analysis, "category"),
                "true_subcategory": hierarchy_value(analysis, "subcategory"),
                "true_case": hierarchy_value(analysis, "case"),

                "predicted_relevance": "",
                "predicted_sentiment": "",
                "predicted_message_type": "",
                "predicted_category": "",
                "predicted_subcategory": "",
                "predicted_case": "",

                "classification_source": str(getattr(analysis, "classification_source", "") or ""),
                "classification_state": str(getattr(analysis, "classification_state", "") or ""),
            }
        )

        print(hierarchy_value(analysis, "subcategory"))
    return rows

async def main(LIMIT=LIMIT, ONLY_WITH_ANALYSIS=None) -> None:
    async with async_session_maker() as db:
        rows = await load_rows(
            db,
            limit=LIMIT,
            only_with_analysis=ONLY_WITH_ANALYSIS,
        )

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)

    with OUTPUT.open(
        "w",
        newline="",
        encoding="utf-8-sig",
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=CSV_COLUMNS,
        )
        writer.writeheader()
        writer.writerows(rows)

    print(f"Exported {len(rows)} rows to {OUTPUT}")

if __name__ == "__main__":
    asyncio.run(main())
