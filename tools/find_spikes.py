"""Ретро-поиск всплесков обращений: дни, когда паблик получил аномально много.

По каждому паблику считает дневные число обращений (канон проекта), находит дни
с превышением нормы (среднее + 3σ, минимум MIN_APPEALS), печатает топ с примерами
текстов. Для презентации: кейсы «система сама увидела событие в день события».

Запуск:  python -m tools.find_spikes [--since 2025-06-01] [--top 15]

Если базы под рукой нет (она на сервере), те же всплески считаются по API:
    python -m tools.find_spikes --base-url https://sigma.krskcit.ru --email me@krskcit.ru
Примеров текстов в этом режиме не будет — ручка отдаёт только счётчики.
"""
from __future__ import annotations

import argparse
import asyncio
import getpass
import statistics
from collections import defaultdict
from datetime import date

from sqlalchemy import text

from backend.db.database import async_session_maker
from backend.modules.analytics.constants import APPEAL_MESSAGE_TYPES

MIN_APPEALS = 8   # меньше в день — не всплеск, шум
SAMPLES = 5       # примеров текста на кейс


async def main(since: str, top: int):
    async with async_session_maker() as db:
        params = {"types": list(APPEAL_MESSAGE_TYPES), "since": date.fromisoformat(since)}
        spikes = (await db.execute(text("""
            WITH daily AS (
                SELECT date_trunc('day', COALESCE(c.comment_date, c.created_at))::date AS d,
                       p.name AS public,
                       count(*) FILTER (WHERE ca.relevance = 'relevant' AND ca.message_type = ANY(:types)
                           AND COALESCE(ca.is_official_response, false) = false
                           AND (c.author_external_id IS NULL OR c.author_external_id NOT LIKE '-%')) AS appeals
                FROM comments c
                JOIN comment_analysis ca ON ca.comment_id = c.id
                JOIN publications pub ON pub.id = c.publication_id
                JOIN public_social_links psl ON psl.id = pub.public_social_link_id
                JOIN publics p ON p.id = psl.public_id
                WHERE c.is_deleted = false AND ca.classification_state = 'done'
                  AND COALESCE(c.comment_date, c.created_at) >= :since
                GROUP BY d, p.name
            ),
            stats AS (SELECT public, avg(appeals) AS mu, stddev(appeals) AS sd FROM daily GROUP BY public)
            SELECT daily.d, daily.public, daily.appeals, round(stats.mu, 1) AS avg
            FROM daily JOIN stats USING (public)
            WHERE daily.appeals >= :min_a AND daily.appeals > stats.mu + 3 * COALESCE(stats.sd, 0)
            ORDER BY daily.appeals / GREATEST(stats.mu, 0.5) DESC
            LIMIT :top
        """), {**params, "min_a": MIN_APPEALS, "top": top})).fetchall()

        if not spikes:
            print("Всплесков не найдено (мало данных за период?)")
            return

        for d, pub, n, avg in spikes:
            ratio = n / max(float(avg), 0.5)
            print(f"\n=== {d} · {pub} — {n} обращений (норма {avg}/день, ×{ratio:.0f}) ===")
            rows = (await db.execute(text("""
                SELECT left(regexp_replace(c.text, E'[\\n\\r]+', ' ', 'g'), 120)
                FROM comments c
                JOIN comment_analysis ca ON ca.comment_id = c.id
                JOIN publications pub ON pub.id = c.publication_id
                JOIN public_social_links psl ON psl.id = pub.public_social_link_id
                JOIN publics p ON p.id = psl.public_id
                WHERE c.is_deleted = false AND p.name = :pub
                  AND date_trunc('day', COALESCE(c.comment_date, c.created_at))::date = :d
                  AND ca.relevance = 'relevant' AND ca.message_type = ANY(:types)
                  AND COALESCE(ca.is_official_response, false) = false
                ORDER BY length(c.text) DESC LIMIT :n
            """), {"pub": pub, "d": d, "types": params["types"], "n": SAMPLES})).fetchall()
            for (t,) in rows:
                print(f"   · {t}")


def find_spikes_api(base_url: str, email: str, password: str, since: str, top: int,
                    *, min_appeals: int = MIN_APPEALS, sigma: float = 3.0,
                    min_ratio: float = 0.0, public_filter: str = "") -> None:
    """Те же всплески, но по данным ручки /api/analytics/appeals/daily."""
    import httpx

    with httpx.Client(base_url=base_url.rstrip("/"), timeout=120.0) as client:
        auth = client.post("/api/auth/login", json={"email": email, "password": password})
        auth.raise_for_status()
        token = auth.json()["access_token"]

        response = client.get(
            "/api/analytics/appeals/daily",
            params={"since": since},
            headers={"Authorization": f"Bearer {token}"},
        )
        response.raise_for_status()
        rows = response.json()

    by_public: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for row in rows:
        by_public[row["public"]].append((row["day"], row["appeals"]))

    spikes = []
    for public, days in by_public.items():
        if public_filter and public_filter.lower() not in public.lower():
            continue
        counts = [appeals for _, appeals in days]
        mu = statistics.fmean(counts)
        sd = statistics.stdev(counts) if len(counts) > 1 else 0.0
        for day, appeals in days:
            ratio = appeals / max(mu, 0.5)
            if appeals >= min_appeals and appeals > mu + sigma * sd and ratio >= min_ratio:
                spikes.append((ratio, day, public, appeals, round(mu, 1)))

    if not spikes:
        print("Всплесков не найдено (мало данных за период?)")
        return

    # top=0 — выводить все: при мягком пороге список нужен целиком,
    # обрезка по кратности прячет события на тихих площадках.
    selected = sorted(spikes, reverse=True)
    if top:
        selected = selected[:top]
    for ratio, day, public, appeals, mu in selected:
        print(f"{day} · {public} — {appeals} обращений (норма {mu}/день, ×{ratio:.1f})")
    print(f"\nвсего: {len(selected)} из {len(spikes)} найденных")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="2025-06-01")
    ap.add_argument("--top", type=int, default=15, help="0 — выводить все")
    ap.add_argument("--min-appeals", type=int, default=MIN_APPEALS,
                    help="меньше обращений в день — считаем шумом")
    ap.add_argument("--sigma", type=float, default=3.0, help="во сколько сигм от нормы")
    ap.add_argument("--min-ratio", type=float, default=0.0, help="минимальная кратность к норме")
    ap.add_argument("--public", default="", help="только площадки, содержащие подстроку")
    ap.add_argument("--base-url", help="считать через API, а не из базы")
    ap.add_argument("--email")
    ap.add_argument("--password")
    a = ap.parse_args()

    if a.base_url:
        if not a.email:
            ap.error("с --base-url нужен --email")
        find_spikes_api(
            a.base_url, a.email, a.password or getpass.getpass("Пароль: "), a.since, a.top,
            min_appeals=a.min_appeals, sigma=a.sigma, min_ratio=a.min_ratio,
            public_filter=a.public,
        )
    else:
        asyncio.run(main(a.since, a.top))
