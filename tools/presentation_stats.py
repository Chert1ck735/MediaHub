"""Цифры для презентации: масштаб потока, обращения, безответные, топ болей.

Определение обращения — канон проекта (как /summary и SLA): relevant + appeal_types
+ done + не официальный ответ + не ответ сообщества. Считает по ВСЕМ организациям.

Запуск:  python -m tools.presentation_stats
"""
from __future__ import annotations

import asyncio

from sqlalchemy import text

from backend.db.database import async_session_maker
from backend.modules.analytics.constants import APPEAL_MESSAGE_TYPES

SEC_PER_COMMENT = 30  # оценка ручного чтения одного коммента


async def main():
    async with async_session_maker() as db:
        async def q(sql, **params):
            return (await db.execute(text(sql), params)).fetchall()

        appeal = {"types": list(APPEAL_MESSAGE_TYPES)}

        [(total, first, last)] = await q(
            "SELECT count(*), min(COALESCE(comment_date, created_at)), max(COALESCE(comment_date, created_at)) "
            "FROM comments WHERE is_deleted = false"
        )
        [(pubs, publics)] = await q(
            "SELECT count(DISTINCT pub.id), count(DISTINCT p.id) FROM publications pub "
            "JOIN public_social_links psl ON psl.id = pub.public_social_link_id "
            "JOIN publics p ON p.id = psl.public_id"
        )
        [(classified,)] = await q(
            "SELECT count(*) FROM comment_analysis WHERE classification_state = 'done'"
        )
        [(appeals,)] = await q(
            """
            SELECT count(*) FROM comments c
            JOIN comment_analysis ca ON ca.comment_id = c.id
            WHERE c.is_deleted = false AND ca.classification_state = 'done'
              AND ca.relevance = 'relevant' AND ca.message_type = ANY(:types)
              AND COALESCE(ca.is_official_response, false) = false
              AND (c.author_external_id IS NULL OR c.author_external_id NOT LIKE '-%')
            """,
            **appeal,
        )
        [(unanswered,)] = await q(
            """
            SELECT count(*) FROM comments c
            JOIN comment_analysis ca ON ca.comment_id = c.id
            WHERE c.is_deleted = false AND ca.classification_state = 'done'
              AND ca.relevance = 'relevant' AND ca.message_type = ANY(:types)
              AND COALESCE(ca.is_official_response, false) = false
              AND (c.author_external_id IS NULL OR c.author_external_id NOT LIKE '-%')
              AND NOT EXISTS (
                  SELECT 1 FROM comments r
                  JOIN comment_analysis ra ON ra.comment_id = r.id
                  WHERE r.parent_comment_id = c.id AND ra.is_official_response = true
              )
            """,
            **appeal,
        )
        top_cat = await q(
            """
            SELECT ca.hierarchy->>'category' AS cat, count(*) AS n FROM comments c
            JOIN comment_analysis ca ON ca.comment_id = c.id
            WHERE c.is_deleted = false AND ca.classification_state = 'done'
              AND ca.relevance = 'relevant' AND ca.message_type = ANY(:types)
              AND COALESCE(ca.is_official_response, false) = false
              AND (c.author_external_id IS NULL OR c.author_external_id NOT LIKE '-%')
              AND COALESCE(ca.hierarchy->>'category', '') <> ''
            GROUP BY cat ORDER BY n DESC LIMIT 8
            """,
            **appeal,
        )
        month = await q(
            """
            SELECT to_char(date_trunc('month', COALESCE(c.comment_date, c.created_at)), 'YYYY-MM') AS m,
                   count(*) AS total,
                   count(*) FILTER (WHERE ca.relevance = 'relevant' AND ca.message_type = ANY(:types)
                       AND COALESCE(ca.is_official_response, false) = false
                       AND (c.author_external_id IS NULL OR c.author_external_id NOT LIKE '-%')) AS appeals
            FROM comments c
            JOIN comment_analysis ca ON ca.comment_id = c.id
            WHERE c.is_deleted = false AND ca.classification_state = 'done'
            GROUP BY m ORDER BY m DESC LIMIT 6
            """,
            **appeal,
        )

        per_day = await q(
            """
            SELECT ROUND(count(*)::numeric / GREATEST(count(DISTINCT date_trunc('day', COALESCE(c.comment_date, c.created_at))), 1), 1)
            FROM comments c
            WHERE c.is_deleted = false
              AND COALESCE(c.comment_date, c.created_at) >= now() - interval '90 days'
            """
        )
        top_publics = await q(
            """
            SELECT p.name, count(*) AS total,
                   count(*) FILTER (WHERE ca.relevance = 'relevant' AND ca.message_type = ANY(:types)
                       AND COALESCE(ca.is_official_response, false) = false
                       AND (c.author_external_id IS NULL OR c.author_external_id NOT LIKE '-%')) AS appeals
            FROM comments c
            JOIN comment_analysis ca ON ca.comment_id = c.id
            JOIN publications pub ON pub.id = c.publication_id
            JOIN public_social_links psl ON psl.id = pub.public_social_link_id
            JOIN publics p ON p.id = psl.public_id
            WHERE c.is_deleted = false AND ca.classification_state = 'done'
            GROUP BY p.name ORDER BY total DESC LIMIT 12
            """,
            **appeal,
        )

        hours = total * SEC_PER_COMMENT / 3600
        print("=== ЦИФРЫ ДЛЯ ПРЕЗЕНТАЦИИ ===")
        print(f"Пабликов: {publics} · публикаций: {pubs}")
        print(f"Комментариев собрано: {total}  (период: {first:%d.%m.%Y} — {last:%d.%m.%Y})" if first else f"Комментариев собрано: {total}")
        print(f"Классифицировано: {classified}")
        print(f"Значимых сообщений аудитории: {appeals}  ({appeals / classified * 100:.0f}% от классифицированных)" if classified else "")
        if appeals:
            print(f"БЕЗ ответа организации: {unanswered}  ({unanswered / appeals * 100:.0f}% обращений)")
        print(f"Ручное чтение всего потока: ~{hours:.0f} чел.-часов  (по {SEC_PER_COMMENT}с на коммент) = ~{hours / 8:.0f} рабочих дней одного человека")
        print("\nТоп тем обращений:")
        for cat, n in top_cat:
            print(f"  {n:5}  {cat}")
        if per_day and per_day[0][0] is not None:
            print(f"\nВ среднем комментариев в день (последние 90 дней): {per_day[0][0]}")
        print("\nТоп пабликов (комментов / из них обращений):")
        for name, t, a in top_publics:
            print(f"  {t:6} / {a:<5}  {name}")
        print("\nПо месяцам (комментов / из них обращений):")
        for m, t, a in month:
            print(f"  {m}: {t} / {a}")


if __name__ == "__main__":
    asyncio.run(main())
