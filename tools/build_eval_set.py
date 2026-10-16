"""Собирает эталонный набор для оценки качества классификации болей.

Берёт сырую выборку реальных VK-комментов, сбалансированную по пабликам
(каждый паблик представлен ~равномерно), независимо от того, классифицированы
они или нет. Экспортирует в CSV (для разметки куратором) и JSONL. Колонки
gold_* заполняет разметчик (агенты или куратор) — это ground truth.
sys_* — текущее решение классификатора (может быть пустым у неклассиф.).

Запуск:  python -m tools.build_eval_set [N_на_паблик]
"""
from __future__ import annotations

import asyncio
import csv
import json
import sys
from pathlib import Path

from sqlalchemy import func, select

from backend.db.comment_analysis import CommentAnalysis
from backend.db.comments import Comment
from backend.db.database import async_session_maker
from backend.db.public_social_links import PublicSocialLink
from backend.db.publics import Public
from backend.db.publications import Publication
from backend.db.social_networks import SocialNetwork

OUT_DIR = Path("data/eval")


async def _sample(session, public_id, limit: int):
    stmt = (
        select(Comment, CommentAnalysis, Public.name.label("public_name"))
        .join(Publication, Publication.id == Comment.publication_id)
        .join(PublicSocialLink, PublicSocialLink.id == Publication.public_social_link_id)
        .join(SocialNetwork, SocialNetwork.id == PublicSocialLink.social_network_id)
        .join(Public, Public.id == PublicSocialLink.public_id)
        .outerjoin(CommentAnalysis, CommentAnalysis.comment_id == Comment.id)
        .where(Comment.is_deleted.is_(False))
        .where(SocialNetwork.code == "vk")
        .where(PublicSocialLink.public_id == public_id)
        .where(func.length(func.coalesce(Comment.text, "")) > 10)
        .order_by(func.random())
        .limit(limit)
    )
    return (await session.execute(stmt)).all()


async def main(per_public: int) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []
    async with async_session_maker() as session:
        publics = (await session.execute(select(Public.id, Public.name))).all()
        for public_id, _name in publics:
            for comment, analysis, public_name in await _sample(session, public_id, per_public):
                hierarchy = (analysis.hierarchy if analysis else None) or {}
                rows.append({
                    "comment_id": str(comment.id),
                    "public": public_name or "",
                    "text": " ".join((comment.text or "").split()),
                    "sys_relevance": getattr(getattr(analysis, "relevance", None), "value", "") or "",
                    "sys_source": (getattr(analysis, "classification_source", "") if analysis else "") or "",
                    "sys_category": hierarchy.get("category", ""),
                    "sys_subcategory": hierarchy.get("subcategory", ""),
                    "sys_case": hierarchy.get("case", ""),
                    "sys_msg_type": (getattr(analysis, "message_type", "") if analysis else "") or "",
                    "gold_is_pain": "",
                    "gold_category": "",
                    "gold_subcategory": "",
                    "gold_case": "",
                    "gold_noise": "",
                    "gold_notes": "",
                })

    csv_path = OUT_DIR / "eval_set.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    jsonl_path = OUT_DIR / "eval_set.jsonl"
    with jsonl_path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    import collections
    by_pub = collections.Counter(r["public"] for r in rows)
    print(f"Записано {len(rows)} строк из {len(by_pub)} пабликов:")
    for pub, c in by_pub.most_common():
        print(f"  {c:>3}  {pub[:45]}")
    print(f"  {csv_path}\n  {jsonl_path}")


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    asyncio.run(main(n))
