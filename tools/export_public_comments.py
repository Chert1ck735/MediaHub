"""Экспорт ВСЕХ комментариев одной площадки + их классификации в CSV.

В отличие от audit_classification.py (только комменты, привязанные к болям),
этот выгружает все Comment площадки вместе с CommentAnalysis — включая
offtopic/irrelevant — чтобы можно было глазами оценить качество разметки
целиком, а не только релевантный срез.

Использование:
    python tools/export_public_comments.py --domain digitalkrsk24
    python tools/export_public_comments.py --domain digitalkrsk24 --out out.csv
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import select

from backend.db.comment_analysis import CommentAnalysis
from backend.db.comments import Comment
from backend.db.database import async_session_maker
from backend.db.public_social_links import PublicSocialLink
from backend.db.publications import Publication
from backend.db.publics import Public
from backend.db.social_networks import SocialNetwork


def _h(analysis: CommentAnalysis | None, key: str) -> str:
    if analysis is None:
        return ""
    h = getattr(analysis, "hierarchy", None) or {}
    if not isinstance(h, dict):
        return ""
    return str(h.get(key) or "")


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--domain", default="digitalkrsk24",
                    help="подстрока url площадки (по умолчанию digitalkrsk24)")
    ap.add_argument("--out", default=None, help="путь к CSV (по умолчанию <domain>_all_comments.csv)")
    args = ap.parse_args()
    out_path = Path(args.out) if args.out else ROOT / f"{args.domain}_all_comments.csv"

    async with async_session_maker() as db:
        rows = (await db.execute(
            select(
                Comment,
                Publication.url.label("publication_url"),
                Public.name.label("public_name"),
            )
            .join(Publication, Publication.id == Comment.publication_id)
            .join(PublicSocialLink, PublicSocialLink.id == Publication.public_social_link_id)
            .join(SocialNetwork, SocialNetwork.id == PublicSocialLink.social_network_id)
            .join(Public, Public.id == PublicSocialLink.public_id)
            .where(SocialNetwork.code == "vk")
            .where(PublicSocialLink.url.ilike(f"%{args.domain}%"))
            .where(Comment.is_deleted.is_(False))
            .order_by(Comment.comment_date.asc().nulls_last(), Comment.created_at.asc())
        )).all()

        comment_ids = [r.Comment.id for r in rows]
        analyses: dict = {}
        if comment_ids:
            res = await db.execute(
                select(CommentAnalysis).where(CommentAnalysis.comment_id.in_(comment_ids))
            )
            analyses = {a.comment_id: a for a in res.scalars().all()}

    fields = [
        "comment_id", "comment_date", "is_reply", "author_name", "author_type",
        "relevance", "message_type", "sentiment", "is_official_response",
        "category", "subcategory", "case", "has_analysis", "text", "publication_url",
    ]
    n_analyzed = 0
    with out_path.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        for r in rows:
            c = r.Comment
            a = analyses.get(c.id)
            if a is not None:
                n_analyzed += 1
            w.writerow({
                "comment_id": str(c.id),
                "comment_date": (c.comment_date or c.created_at).isoformat() if (c.comment_date or c.created_at) else "",
                "is_reply": bool(getattr(c, "parent_comment_id", None)),
                "author_name": getattr(c, "author_name", "") or "",
                "author_type": getattr(a, "author_type", "") or "" if a else "",
                "relevance": getattr(getattr(a, "relevance", None), "value", "") if a and getattr(a, "relevance", None) is not None else "",
                "message_type": getattr(a, "message_type", "") or "" if a else "",
                "sentiment": getattr(getattr(a, "sentiment", None), "value", "") if a and getattr(a, "sentiment", None) is not None else "",
                "is_official_response": bool(getattr(a, "is_official_response", False)) if a else "",
                "category": _h(a, "category"),
                "subcategory": _h(a, "subcategory"),
                "case": _h(a, "case"),
                "has_analysis": a is not None,
                "text": (c.text or "").replace("\n", " ").strip(),
                "publication_url": r.publication_url or "",
            })

    print(f"Exported {len(rows)} comments ({n_analyzed} with analysis) -> {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
