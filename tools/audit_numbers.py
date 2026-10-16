"""Сквозная проверка сходимости чисел на реальной БД.

Запуск из корня проекта: python -m tools.audit_numbers
Гоняет боевые сервисы аналитики по всем периодам и проверяет инварианты,
которые должны выполняться всегда. Ничего не меняет, только читает.
"""
import asyncio
from sqlalchemy import select

from backend.db.database import async_session_maker
from backend.db.users import User
from backend.modules.analytics.services.pain_list_service import PainListService
from backend.modules.analytics.services.summary_service import AnalyticsSummaryService
from backend.modules.report.repositories.post_repository import ReportPostRepository

from sqlalchemy import text

from backend.modules.analytics.utils.time_helpers import period_to_since

PERIODS = ["week", "month", "3months", "6months", "year", "all"]


async def distinct_pain_comments(db, *, since) -> int:
    """Уникальные комментарии, привязанные к болям, в том же скоупе обращения."""

    sql = text("""
        SELECT count(DISTINCT cp.comment_id)
        FROM comment_pains cp
        JOIN comments c ON c.id = cp.comment_id
        JOIN comment_analysis ca ON ca.comment_id = c.id
        WHERE c.is_deleted = false
          AND ca.classification_state = 'done'
          AND ca.relevance = 'relevant'
          AND ca.message_type IN ('complaint','sarcasm','request')
          AND COALESCE(ca.is_official_response, false) = false
          AND (c.author_external_id IS NULL OR c.author_external_id NOT LIKE '-%')
          AND (CAST(:since AS timestamptz) IS NULL
               OR COALESCE(c.comment_date, c.created_at) >= CAST(:since AS timestamptz))
    """)
    return int((await db.execute(sql, {"since": since})).scalar() or 0)

problems: list[str] = []


def check(label: str, ok: bool, detail: str) -> None:
    mark = "OK  " if ok else "!!! "
    print(f"  {mark}{label}: {detail}")
    if not ok:
        problems.append(f"{label} — {detail}")


async def main() -> None:
    async with async_session_maker() as db:
        user = (await db.execute(select(User).limit(1))).scalar_one()
        print(f"организация: {user.organization_id}\n")

        summary_service = AnalyticsSummaryService(db)
        pain_service = PainListService(db)
        posts_repo = ReportPostRepository(db)

        for period in PERIODS:
            print(f"=== период {period} ===")
            summary = await summary_service.get_summary(user, period=period)

            sentiment = summary.sentiment_breakdown
            sentiment_sum = sentiment.positive + sentiment.neutral + sentiment.negative
            types_sum = summary.appeal_count + summary.gratitude_count + summary.other_count

            check(
                "типы = классифицировано",
                types_sum == summary.classified_comment_count,
                f"{summary.appeal_count}+{summary.gratitude_count}+{summary.other_count}"
                f"={types_sum} vs {summary.classified_comment_count}",
            )
            check(
                "тональность = классифицировано",
                sentiment_sum == summary.classified_comment_count,
                f"{sentiment_sum} vs {summary.classified_comment_count}",
            )
            check(
                "SLA считает те же обращения",
                summary.sla.appeals == summary.appeal_count,
                f"SLA {summary.sla.appeals} vs обращений {summary.appeal_count}",
            )
            check(
                "жалобы+просьбы = обращения",
                summary.complaint_count + summary.request_count == summary.appeal_count,
                f"{summary.complaint_count}+{summary.request_count} vs {summary.appeal_count}",
            )
            categories_sum = sum(item.count for item in summary.category_breakdown)
            check(
                "категории <= обращений",
                categories_sum <= summary.appeal_count,
                f"топ-категорий {categories_sum} (показаны 8 из всех) vs обращений {summary.appeal_count}",
            )
            check(
                "классифицировано <= собрано",
                summary.classified_comment_count <= summary.total_comment_count,
                f"{summary.classified_comment_count} <= {summary.total_comment_count}",
            )
            check(
                "отвечено <= обращений",
                summary.sla.answered <= summary.sla.appeals,
                f"{summary.sla.answered} <= {summary.sla.appeals}",
            )

            pains = await pain_service.list_pains(user, period=period)
            mentions_sum = sum(p.mentions_count for p in pains)
            # один комментарий может лежать в двух болях, поэтому сравнивать с
            # обращениями надо уникальные комментарии, а не сумму по карточкам
            unique_in_pains = await distinct_pain_comments(db, since=period_to_since(period))
            check(
                "комментарии болей <= обращений",
                unique_in_pains <= summary.appeal_count,
                f"уникальных в болях {unique_in_pains} <= обращений {summary.appeal_count}"
                f" (сумма по карточкам {mentions_sum}, пересечений {mentions_sum - unique_in_pains})",
            )

            posts = await posts_repo.load_vk_posts(user.organization_id, period=period)
            vk_comments = sum(int(p.get("comments") or 0) for p in posts)
            # для коротких периодов сравнение некорректно: посты фильтруются по дате
            # поста, а собранные комментарии — по дате комментария
            if period in {"all", "year"}:
                check(
                    "счётчик VK >= собрано",
                    vk_comments >= summary.total_comment_count,
                    f"VK {vk_comments} vs собрано {summary.total_comment_count} "
                    f"({round(summary.total_comment_count / vk_comments * 100) if vk_comments else 0}% полнота)",
                )
            print(f"      постов {len(posts)}, собрано {summary.total_comment_count}, "
                  f"классиф. {summary.classified_comment_count}, обращений {summary.appeal_count}")
            print()

    print("=" * 70)
    if problems:
        print(f"ПРОБЛЕМ: {len(problems)}")
        for item in problems:
            print(" -", item)
    else:
        print("Все инварианты сошлись.")


asyncio.run(main())
