"""Полнота сбора комментариев: счётчик VK против того, что лежит в БД.

По каждой подключённой ссылке берёт N последних постов ИЗ БАЗЫ, спрашивает у VK
актуальное `comments.count` (wall.getById, пачками по 100) и сравнивает.

Гипотеза, ради которой писалось: комментарии дописывают уже ПОСЛЕ сбора. Проверка —
прогнать, через два дня прогнать повторно и сравнить два CSV (`--compare`).

VK считает в `comments.count` и комментарии без текста (стикер, картинка), которые
мы не храним, — 100% недостижимы. Смотреть надо динамику, а не абсолют.

Запуск:
    python -m tools.check_collection_completeness
    python -m tools.check_collection_completeness --posts 50 --since 2026-06-01
    python -m tools.check_collection_completeness --compare data/completeness/completeness_2026-08-17.csv
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import sys
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

from sqlalchemy import text

from backend.db.database import async_session_maker
from backend.modules.vk.utils.api_client import VkApiClient
from backend.modules.vk.utils.errors import VkApiError

OUT_DIR = Path("data/completeness")
VK_BATCH = 100  # wall.getById принимает до 100 постов за вызов

FIELDS = [
    "public", "external_post_id", "post_url", "published_at",
    "vk_count", "db_count", "diff", "pct",
]


async def load_posts(db, posts_per_public: int, since: date | None) -> list[dict]:
    """Последние N постов по каждой активной ссылке + число комментов в БД."""

    rows = (await db.execute(text("""
        WITH ranked AS (
            SELECT pub.id            AS publication_id,
                   pub.external_post_id,
                   pub.url,
                   pub.published_at,
                   p.name            AS public,
                   row_number() OVER (
                       PARTITION BY psl.id ORDER BY pub.published_at DESC NULLS LAST
                   ) AS rn
            FROM publications pub
            JOIN public_social_links psl ON psl.id = pub.public_social_link_id
            JOIN publics p ON p.id = psl.public_id
            WHERE psl.is_active = true
              AND pub.external_post_id IS NOT NULL
              AND (CAST(:since AS timestamptz) IS NULL OR pub.published_at >= CAST(:since AS timestamptz))
        )
        SELECT r.public, r.external_post_id, r.url, r.published_at,
               count(c.id) FILTER (WHERE c.is_deleted = false) AS db_count
        FROM ranked r
        LEFT JOIN comments c ON c.publication_id = r.publication_id
        WHERE r.rn <= :limit
        GROUP BY r.public, r.external_post_id, r.url, r.published_at
        ORDER BY r.public, r.published_at DESC
    """), {"limit": posts_per_public, "since": since})).fetchall()

    return [
        {
            "public": r.public,
            "external_post_id": r.external_post_id,
            "post_url": r.url or "",
            "published_at": r.published_at.isoformat() if r.published_at else "",
            "db_count": int(r.db_count or 0),
        }
        for r in rows
    ]


def fetch_vk_counts(client: VkApiClient, external_ids: list[str]) -> dict[str, int]:
    """external_post_id ('-123_456') -> актуальный comments.count из VK."""

    counts: dict[str, int] = {}
    for start in range(0, len(external_ids), VK_BATCH):
        batch = external_ids[start:start + VK_BATCH]
        try:
            response = client.call("wall.getById", {"posts": ",".join(batch)})
        except VkApiError as exc:
            print(f"  ! пачка {start // VK_BATCH + 1}: {exc}", file=sys.stderr)
            continue
        items = response.get("items", []) if isinstance(response, dict) else (response or [])
        for item in items:
            key = f"{item.get('owner_id')}_{item.get('id')}"
            counts[key] = int((item.get("comments") or {}).get("count") or 0)
        print(f"  пачка {start // VK_BATCH + 1}: {len(items)} постов", flush=True)
    return counts


def summarize(rows: list[dict]) -> tuple[list[tuple], tuple]:
    """Полнота по пабликам и общая. Посты, пропавшие из VK, не учитываются."""

    per_public: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])  # vk, db, posts
    for row in rows:
        if row["vk_count"] is None:
            continue
        agg = per_public[row["public"]]
        agg[0] += row["vk_count"]
        agg[1] += row["db_count"]
        agg[2] += 1

    per_rows = sorted(
        (
            (name, posts, vk, db, db - vk, (db / vk * 100) if vk else 100.0)
            for name, (vk, db, posts) in per_public.items()
        ),
        key=lambda r: r[5],
    )
    tot_vk = sum(r[2] for r in per_rows)
    tot_db = sum(r[3] for r in per_rows)
    total = ("ИТОГО", sum(r[1] for r in per_rows), tot_vk, tot_db,
             tot_db - tot_vk, (tot_db / tot_vk * 100) if tot_vk else 100.0)
    return per_rows, total


def print_report(rows: list[dict], per_rows: list[tuple], total: tuple, worst: int) -> None:
    missing = [r for r in rows if r["vk_count"] is None]
    gaps = sorted(
        (r for r in rows if r["vk_count"]),
        key=lambda r: r["db_count"] - r["vk_count"],
    )[:worst]

    print(f"\nХудшие посты по недобору (топ {worst}):")
    print(f"{'паблик':<28} {'пост':<16} {'VK':>6} {'БД':>6} {'разн':>6} {'%':>7}")
    for r in gaps:
        pct = r["db_count"] / r["vk_count"] * 100
        print(f"{r['public'][:28]:<28} {r['external_post_id']:<16} "
              f"{r['vk_count']:>6} {r['db_count']:>6} "
              f"{r['db_count'] - r['vk_count']:>6} {pct:>6.1f}%")

    print("\nПолнота по пабликам:")
    print(f"{'паблик':<28} {'постов':>7} {'VK':>8} {'БД':>8} {'разн':>7} {'%':>7}")
    for name, posts, vk, db, diff, pct in per_rows + [total]:
        print(f"{name[:28]:<28} {posts:>7} {vk:>8} {db:>8} {diff:>7} {pct:>6.1f}%")

    if missing:
        print(f"\nНет в выдаче VK (удалены/скрыты): {len(missing)} постов")


def save_csv(rows: list[dict], per_rows: list[tuple], total: tuple, stamp: str) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"completeness_{stamp}.csv"
    with path.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.writer(fh, delimiter=";")
        writer.writerow(FIELDS)
        for r in rows:
            vk = r["vk_count"]
            writer.writerow([
                r["public"], r["external_post_id"], r["post_url"], r["published_at"],
                "" if vk is None else vk, r["db_count"],
                "" if vk is None else r["db_count"] - vk,
                "" if not vk else f"{r['db_count'] / vk * 100:.1f}",
            ])
        writer.writerow([])
        writer.writerow(["ИТОГ ПО ПАБЛИКАМ", "постов", "vk", "db", "diff", "pct"])
        for name, posts, vk, db, diff, pct in per_rows + [total]:
            writer.writerow([name, posts, vk, db, diff, f"{pct:.1f}"])
    return path


def compare(prev_path: Path, rows: list[dict]) -> None:
    """Сравнение с прошлым прогоном — проверка гипотезы о дописывании."""

    with prev_path.open(encoding="utf-8-sig") as fh:
        prev = {
            r["external_post_id"]: r
            for r in csv.DictReader(fh, delimiter=";")
            if r.get("external_post_id") and r.get("vk_count")
        }

    grew_vk = grew_db = caught_up = 0
    lag: list[tuple] = []
    for row in rows:
        old = prev.get(row["external_post_id"])
        if not old or row["vk_count"] is None:
            continue
        d_vk = row["vk_count"] - int(old["vk_count"])
        d_db = row["db_count"] - int(old["db_count"])
        if d_vk > 0:
            grew_vk += d_vk
        if d_db > 0:
            grew_db += d_db
        if d_vk > 0 and d_db >= d_vk:
            caught_up += 1
        elif d_vk > d_db:
            lag.append((row["public"], row["external_post_id"], d_vk, d_db))

    print(f"\nСравнение с {prev_path.name} (общих постов: "
          f"{sum(1 for r in rows if r['external_post_id'] in prev)}):")
    print(f"  прибавилось комментов в VK: {grew_vk}")
    print(f"  прибавилось комментов в БД: {grew_db}")
    print(f"  постов, где сбор догнал прирост: {caught_up}")
    print(f"  постов, где сбор отстал:        {len(lag)}")
    if grew_vk:
        print(f"  доля прироста, попавшая в БД: {grew_db / grew_vk * 100:.1f}%")
    for public, ext, d_vk, d_db in sorted(lag, key=lambda x: x[3] - x[2])[:15]:
        print(f"    {public[:28]:<28} {ext:<16} VK +{d_vk:<5} БД +{d_db}")

    if grew_vk and grew_db / grew_vk < 0.5:
        print("\n  ВЫВОД: гипотеза подтверждается — комментарии дописывают, "
              "а дозагрузка их не добирает.")
    elif grew_vk:
        print("\n  ВЫВОД: дозагрузка работает; недобор объясняется не дописыванием.")
    else:
        print("\n  ВЫВОД: прироста в VK нет — окно между прогонами мало "
              "либо посты остыли. Повторить позже.")


async def main() -> None:
    parser = argparse.ArgumentParser(description="Полнота сбора: VK против БД")
    parser.add_argument("--posts", type=int, default=30, help="постов на паблик (по умолчанию 30)")
    parser.add_argument("--since", help="брать посты не раньше даты, YYYY-MM-DD")
    parser.add_argument("--worst", type=int, default=15, help="сколько худших постов печатать")
    parser.add_argument("--compare", help="CSV прошлого прогона для сравнения")
    args = parser.parse_args()

    since = date.fromisoformat(args.since) if args.since else None

    async with async_session_maker() as db:
        rows = await load_posts(db, args.posts, since)
    if not rows:
        raise SystemExit("В БД нет постов под эти условия")
    print(f"Постов из БД: {len(rows)} по {len({r['public'] for r in rows})} пабликам")

    client = VkApiClient()
    counts = await asyncio.to_thread(
        fetch_vk_counts, client, [r["external_post_id"] for r in rows]
    )
    for row in rows:
        row["vk_count"] = counts.get(row["external_post_id"])

    per_rows, total = summarize(rows)
    print_report(rows, per_rows, total, args.worst)

    stamp = datetime.now().strftime("%Y-%m-%d")
    path = save_csv(rows, per_rows, total, stamp)
    print(f"\nСохранено: {path}")

    if args.compare:
        compare(Path(args.compare), rows)
    else:
        print(f"Через 2 дня: python -m tools.check_collection_completeness "
              f"--posts {args.posts} --compare {path}")


if __name__ == "__main__":
    asyncio.run(main())
