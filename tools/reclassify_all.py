"""Reclassify all 1083 comments on qwen2.5:7b + new prompt, then auto-rebuild snapshot.

Шаги:
  1. Пометить ВСЕ relevant comment_analysis организации как pending.
  2. В цикле process_pending_batch до picked=0.
  3. Дёрнуть POST /api/analytics/rebuild-vk через JWT — пересоздать snapshot.
  4. Распечатать сравнительную сводку.
"""
import asyncio
import json
import os
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from uuid import UUID

from dotenv import load_dotenv
load_dotenv()

from jose import jwt as pyjwt
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from backend.modules.analytics.classification import process_pending_batch


DB_USER = os.getenv("DB_USER")
DB_PASS = os.getenv("DB_PASS")
DB_HOST = os.getenv("DB_HOST")
DB_PORT = os.getenv("DB_PORT")
DB_NAME = os.getenv("DB_NAME")
ASYNC_URL = f"postgresql+asyncpg://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

ORG_ID = UUID("d97f0d3c-a8cd-4a77-aaf0-07961f4143fe")
USER_ID = "2300199e-1ecc-49f3-88d6-fc16b5bfac74"
USER_EMAIL = "belkovskyy@yandex.ru"
JWT_SECRET = "change-me-in-production-secret-key-32chars"
BATCH_LIMIT = 50
CONCURRENCY = 4


def make_jwt() -> str:
    return pyjwt.encode(
        {"sub": USER_ID, "email": USER_EMAIL, "exp": datetime.now(timezone.utc) + timedelta(hours=2)},
        JWT_SECRET,
        algorithm="HS256",
    )


def snapshot_distributions_sql() -> list[str]:
    return [
        "select classification_source, count(*) from comment_analysis group by 1 order by 2 desc",
        ("select coalesce(json_extract_path_text(hierarchy, 'category'), '<NULL>'), count(*) "
         "from comment_analysis where relevance::text='relevant' group by 1 order by 2 desc"),
        ("select count(*) filter (where coalesce(json_extract_path_text(hierarchy,'case'), '') != '') as with_case, "
         "count(*) as total from comment_analysis where relevance::text='relevant'"),
    ]


async def dump(engine, label: str) -> None:
    print(f"\n=== {label} ===")
    async with engine.begin() as conn:
        for q in snapshot_distributions_sql():
            rows = (await conn.execute(text(q))).all()
            print(f"  --- {q[:90]}...")
            for r in rows:
                print(f"      {tuple(r)}")


async def main() -> None:
    engine = create_async_engine(ASYNC_URL, pool_pre_ping=True)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    t_start = time.time()
    await dump(engine, "BEFORE reclassify")

    # 1. Mark all relevant analyses for this org as pending.
    async with Session() as s:
        res = await s.execute(text("""
            update comment_analysis ca
            set classification_state='pending'
            from comments c
            join publications p on p.id = c.publication_id
            join public_social_links psl on psl.id = p.public_social_link_id
            join publics pu on pu.id = psl.public_id
            where ca.comment_id = c.id
              and ca.relevance::text = 'relevant'
              and pu.organization_id = :org
        """), {"org": str(ORG_ID)})
        await s.commit()
        print(f"\nMarked pending: rowcount={res.rowcount}")

    # 2. Process in batches.
    total = {"picked": 0, "succeeded": 0, "failed": 0, "skipped": 0, "durs_ms": []}
    iteration = 0
    while True:
        iteration += 1
        async with Session() as s:
            stats = await process_pending_batch(
                s, limit=BATCH_LIMIT, organization_id=ORG_ID, concurrency=CONCURRENCY
            )
        d = stats.to_dict()
        elapsed_min = (time.time() - t_start) / 60.0
        print(f"  iter {iteration:3d}  picked={d['picked']:3d}  ok={stats.succeeded:3d}  "
              f"fail={stats.failed:3d}  avg_ms={d['avg_ms']}  elapsed={elapsed_min:.1f}min")
        total["picked"]    += d["picked"]
        total["succeeded"] += stats.succeeded
        total["failed"]    += stats.failed
        total["skipped"]   += stats.skipped
        total["durs_ms"].extend(stats.durations_ms)
        if d["picked"] == 0:
            break

    avg = (sum(total["durs_ms"]) / len(total["durs_ms"])) if total["durs_ms"] else None
    print(f"\nTOTAL: iters={iteration} picked={total['picked']} ok={total['succeeded']} "
          f"fail={total['failed']} skipped={total['skipped']} avg_ms={round(avg,1) if avg else None}")
    print(f"Worker time: {(time.time()-t_start)/60.0:.1f} min")

    await dump(engine, "AFTER reclassify, BEFORE rebuild")

    # 3. Trigger snapshot rebuild via API (with JWT).
    print("\n=== Triggering POST /api/analytics/rebuild-vk ===")
    token = make_jwt()
    req = urllib.request.Request(
        "http://localhost:8000/api/analytics/rebuild-vk?force_reclassify=false",
        method="POST",
        headers={"Authorization": f"Bearer {token}", "Content-Length": "0"},
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            body = resp.read().decode("utf-8")
            print(f"  status: {resp.status}")
            try:
                data = json.loads(body)
                print(f"  body: {json.dumps(data, ensure_ascii=False)[:400]}")
            except Exception:
                print(f"  body (raw): {body[:300]}")
    except Exception as e:
        print(f"  ERROR triggering rebuild: {type(e).__name__}: {e}")

    await dump(engine, "AFTER rebuild")

    # 4. Final pains preview
    print("\n=== Top pains after full cycle ===")
    req2 = urllib.request.Request(
        "http://localhost:8000/api/analytics/pains",
        headers={"Authorization": f"Bearer {token}"},
    )
    try:
        with urllib.request.urlopen(req2, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            for p in data[:7]:
                tc = [c["title"] for c in (p.get("top_cases") or [])][:5]
                print(f"  {p['title']!r}  sev={p['severity_level']}  mentions={p['mentions_count']}  cases={p['cases_count']}  top={tc}")
    except Exception as e:
        print(f"  ERROR: {e}")

    print(f"\nTOTAL WALL TIME: {(time.time()-t_start)/60.0:.1f} min")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
