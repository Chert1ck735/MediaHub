"""Аудит классификации комментариев по болям.

Печатает для каждой pain:
  - её title/category/severity_level из БД
  - список привязанных Comment (через CommentPain) + их CommentAnalysis.hierarchy
  - флаг is_official_response

Назначение — глазами проверить где LLM напортачил: модераторские ответы
помечены как boli, чужие категории, дубли. После аудита можно решить —
просто переклассифицировать (`/api/analytics/reclassify-vk` с scope=all),
расширить таксономию или подкрутить промпт.

Использование:
    python tools/audit_classification.py
    python tools/audit_classification.py --pain "Социальная сфера"
    python tools/audit_classification.py --public-link <UUID>   # фильтр по площадке
    python tools/audit_classification.py --csv out.csv          # экспорт
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
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.comment_analysis import CommentAnalysis
from backend.db.comment_pains import CommentPain
from backend.db.comments import Comment
from backend.db.database import async_session_maker
from backend.db.pains import Pain
from backend.db.public_social_links import PublicSocialLink
from backend.db.publications import Publication
from backend.db.publics import Public


def trim(s: str | None, n: int = 200) -> str:
    s = (s or "").strip().replace("\n", " ")
    return (s[:n] + "…") if len(s) > n else s


async def fetch_audit(
    db: AsyncSession,
    *,
    pain_title: str | None = None,
    public_social_link_id: str | None = None,
) -> list[dict]:
    pain_q = select(Pain).order_by(Pain.mentions_count.desc())
    if pain_title:
        pain_q = pain_q.where(Pain.title.ilike(f"%{pain_title}%"))
    pains = (await db.execute(pain_q)).scalars().all()

    rows: list[dict] = []
    for pain in pains:
        link_filter = ""
        cmt_q = (
            select(
                Comment.id, Comment.text, Comment.author_name,
                Publication.url.label("publication_url"),
                PublicSocialLink.id.label("link_id"),
                Public.name.label("public_name"),
                CommentAnalysis.message_type,
                CommentAnalysis.sentiment,
                CommentAnalysis.relevance,
                CommentAnalysis.is_official_response,
                CommentAnalysis.hierarchy,
                CommentAnalysis.summary,
            )
            .select_from(CommentPain)
            .join(Comment, Comment.id == CommentPain.comment_id)
            .join(Publication, Publication.id == Comment.publication_id, isouter=True)
            .join(PublicSocialLink, PublicSocialLink.id == Publication.public_social_link_id, isouter=True)
            .join(Public, Public.id == PublicSocialLink.public_id, isouter=True)
            .join(CommentAnalysis, CommentAnalysis.comment_id == Comment.id, isouter=True)
            .where(CommentPain.pain_id == pain.id)
            .where(Comment.is_deleted.is_(False))
            .order_by(Comment.comment_date.desc().nulls_last())
        )
        if public_social_link_id:
            import uuid as _u
            cmt_q = cmt_q.where(PublicSocialLink.id == _u.UUID(public_social_link_id))
            link_filter = f" [link={public_social_link_id[:8]}…]"

        comments = (await db.execute(cmt_q)).all()
        if not comments and public_social_link_id:
            continue
        print(f"\n{'=' * 80}")
        print(f"PAIN: «{pain.title}» ({pain.category}) · severity={pain.severity_level.value} · mentions={pain.mentions_count}{link_filter}")
        print(f"comments attached: {len(comments)}")
        print(f"{'-' * 80}")
        for i, c in enumerate(comments, start=1):
            h = c.hierarchy or {}
            cat = (h.get("category") or "—").strip() or "—"
            sub = (h.get("subcategory") or "—").strip() or "—"
            case = (h.get("case") or "—").strip() or "—"
            msg_type = (c.message_type or "—")
            sentiment = c.sentiment.value if c.sentiment else "—"
            rel = c.relevance.value if c.relevance else "—"
            official = "OFFICIAL" if c.is_official_response else ""
            print(
                f"[{i:3}] {rel:<9} {msg_type:<10} {sentiment:<8} {official:<8} "
                f"cat={cat!r} sub={sub!r} case={case!r}"
            )
            print(f"      text: {trim(c.text, 240)}")
            if c.author_name:
                print(f"      author: {c.author_name} · {c.public_name or ''}")
            rows.append({
                "pain_title": pain.title,
                "pain_category": pain.category,
                "pain_severity": pain.severity_level.value,
                "comment_id": str(c.id),
                "relevance": rel,
                "message_type": msg_type,
                "sentiment": sentiment,
                "is_official_response": bool(c.is_official_response),
                "llm_category": cat,
                "llm_subcategory": sub,
                "llm_case": case,
                "text": trim(c.text, 600),
                "author_name": c.author_name or "",
                "public_name": c.public_name or "",
                "publication_url": c.publication_url or "",
            })
    return rows


async def list_links(db: AsyncSession) -> None:
    """Печатает все PublicSocialLink — чтобы достать UUID нужной площадки."""
    rows = await db.execute(
        select(PublicSocialLink.id, PublicSocialLink.url, Public.name)
        .join(Public, Public.id == PublicSocialLink.public_id)
    )
    print(f"{'UUID':<40} {'name':<40} url")
    print("-" * 120)
    for lid, url, name in rows.all():
        print(f"{str(lid):<40} {(name or '')[:38]:<40} {url}")


async def main() -> None:
    p = argparse.ArgumentParser(description="Аудит классификации болей.")
    p.add_argument("--pain", help="фильтр по pain.title (ilike)")
    p.add_argument("--public-link", help="UUID PublicSocialLink")
    p.add_argument("--url", help="искать площадку по подстроке URL (например 'digitalkrsk24')")
    p.add_argument("--list-links", action="store_true", help="показать все площадки и их UUID")
    p.add_argument("--csv", help="экспорт в CSV")
    args = p.parse_args()

    async with async_session_maker() as db:
        if args.list_links:
            await list_links(db)
            return

        link_uuid = args.public_link
        if args.url:
            row = (await db.execute(
                select(PublicSocialLink.id)
                .where(PublicSocialLink.url.ilike(f"%{args.url}%"))
                .limit(1)
            )).first()
            if not row:
                print(f"Не нашёл площадку с URL ilike %{args.url}%. Запусти --list-links.")
                return
            link_uuid = str(row[0])
            print(f"Найдена площадка: {link_uuid}\n")

        rows = await fetch_audit(
            db,
            pain_title=args.pain,
            public_social_link_id=link_uuid,
        )

    if args.csv and rows:
        with open(args.csv, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
        print(f"\n→ Экспортировано {len(rows)} строк в {args.csv}")


if __name__ == "__main__":
    asyncio.run(main())
