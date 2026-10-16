"""
СИГМА: выгрузка агрегатов из БД для обоснования продукта.

Что делает: подключается к Postgres, считает ~12 агрегатов и кладёт их
в CSV. Сырые комментарии и персональные данные НЕ выгружаются — только
счётчики, даты и названия кейсов/категорий.

Запуск (из корня проекта, в venv где стоит asyncpg):
    python tools/sigma_export.py
    python tools/sigma_export.py --label local_old
    python tools/sigma_export.py --dsn postgresql://user:pass@host:5432/dbname

Результат: data/db_export/<label>/*.csv  +  _errors.txt (если что-то не сошлось)
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import os
import sys
from pathlib import Path

try:
    import asyncpg
except ImportError:
    sys.exit("Нет asyncpg. Активируйте venv проекта или: pip install asyncpg")

ROOT = Path(__file__).resolve().parents[1]


def load_env() -> dict:
    env = {}
    p = ROOT / ".env"
    if p.exists():
        for line in p.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def build_dsn(args) -> tuple[str, str]:
    if args.dsn:
        return args.dsn, (args.label or "db")
    env = load_env()
    host = os.getenv("DB_HOST") or env.get("DB_HOST", "localhost")
    port = os.getenv("DB_PORT") or env.get("DB_PORT", "5432")
    name = os.getenv("DB_NAME") or env.get("DB_NAME", "media_project")
    user = os.getenv("DB_USER") or env.get("DB_USER", "postgres")
    pwd = os.getenv("DB_PASS") or env.get("DB_PASS", "")
    return f"postgresql://{user}:{pwd}@{host}:{port}/{name}", (args.label or name)


# --------------------------------------------------------------------------
# Базовый срез. Определения обращения и официального ответа взяты один в один
# из incidents_service.py, чтобы цифры совпадали с тем, что показывает продукт.
# --------------------------------------------------------------------------
BASE_FULL = """
WITH base AS (
    SELECT cm.id,
           cm.comment_date                                   AS d,
           cm.parent_comment_id                              AS pid,
           cm.author_external_id                             AS author,
           psl.id                                            AS link_id,
           coalesce(psl.title, p.name)                       AS public_name,
           sn.code                                           AS network,
           o.name                                            AS org_name,
           ca.message_type                                   AS mtype,
           ca.classification_state                           AS cstate,
           ca.classification_source                          AS csource,
           ca.sentiment::text                                AS sentiment,
           ca.analyzed_at                                    AS analyzed_at,
           ca.model_version                                  AS model_version,
           lower(coalesce(json_extract_path_text(ca.hierarchy,'category'),''))    AS category,
           lower(coalesce(json_extract_path_text(ca.hierarchy,'subcategory'),'')) AS subcategory,
           coalesce(json_extract_path_text(ca.hierarchy,'case'),'')               AS case_name,
           (ca.id IS NOT NULL)                               AS analyzed,
           (coalesce(ca.is_official_response,false)
             OR cm.author_external_id LIKE '-%%')            AS is_official,
           (ca.relevance = 'relevant'
             AND ca.classification_state = 'done'
             AND ca.message_type = ANY(ARRAY['complaint','sarcasm','request'])
             AND coalesce(ca.is_official_response,false) = false
             AND (cm.author_external_id IS NULL OR cm.author_external_id NOT LIKE '-%%')
           )                                                 AS is_appeal
    FROM comments cm
    JOIN publications pub        ON pub.id = cm.publication_id
    JOIN public_social_links psl ON psl.id = pub.public_social_link_id
    JOIN publics p               ON p.id = psl.public_id
    JOIN organizations o         ON o.id = p.organization_id
    JOIN social_networks sn      ON sn.id = psl.social_network_id
    LEFT JOIN comment_analysis ca ON ca.comment_id = cm.id
    WHERE cm.is_deleted = false
),
replies AS (
    SELECT b.pid AS parent_id, min(b.d) AS reply_date
    FROM base b
    WHERE b.pid IS NOT NULL AND b.is_official
    GROUP BY b.pid
),
appeals AS (
    SELECT a.*, r.reply_date,
           CASE WHEN r.reply_date IS NOT NULL AND a.d IS NOT NULL
                THEN extract(epoch FROM (r.reply_date - a.d))/3600.0 END AS reply_hours
    FROM base a
    LEFT JOIN replies r ON r.parent_id = a.id
    WHERE a.is_appeal
)
"""

# Урезанный вариант для старой базы, где нет новых колонок.
BASE_LEGACY = """
WITH base AS (
    SELECT cm.id,
           cm.comment_date                    AS d,
           cm.parent_comment_id               AS pid,
           cm.author_external_id              AS author,
           psl.id                             AS link_id,
           coalesce(psl.title, p.name)        AS public_name,
           sn.code                            AS network,
           o.name                             AS org_name,
           NULL::text                         AS mtype,
           NULL::text                         AS cstate,
           NULL::text                         AS csource,
           ca.sentiment::text                 AS sentiment,
           ca.analyzed_at                     AS analyzed_at,
           ca.model_version                   AS model_version,
           ''::text                           AS category,
           ''::text                           AS subcategory,
           ''::text                           AS case_name,
           (ca.id IS NOT NULL)                AS analyzed,
           (cm.author_external_id LIKE '-%%') AS is_official,
           (ca.relevance = 'relevant'
             AND cm.author_external_id NOT LIKE '-%%')  AS is_appeal
    FROM comments cm
    JOIN publications pub        ON pub.id = cm.publication_id
    JOIN public_social_links psl ON psl.id = pub.public_social_link_id
    JOIN publics p               ON p.id = psl.public_id
    JOIN organizations o         ON o.id = p.organization_id
    JOIN social_networks sn      ON sn.id = psl.social_network_id
    LEFT JOIN comment_analysis ca ON ca.comment_id = cm.id
    WHERE cm.is_deleted = false
),
replies AS (
    SELECT b.pid AS parent_id, min(b.d) AS reply_date
    FROM base b WHERE b.pid IS NOT NULL AND b.is_official GROUP BY b.pid
),
appeals AS (
    SELECT a.*, r.reply_date,
           CASE WHEN r.reply_date IS NOT NULL AND a.d IS NOT NULL
                THEN extract(epoch FROM (r.reply_date - a.d))/3600.0 END AS reply_hours
    FROM base a LEFT JOIN replies r ON r.parent_id = a.id WHERE a.is_appeal
)
"""

QUERIES: list[tuple[str, str, str]] = [
    # (файл, что доказывает, SQL после базового CTE)
    ("01_overview",
     "масштаб потока: сколько всего, за какой период, сколько пабликов",
     """
     SELECT count(*)                                        AS comments_total,
            count(*) FILTER (WHERE analyzed)                AS analyzed_total,
            count(*) FILTER (WHERE is_appeal)               AS appeals_total,
            count(*) FILTER (WHERE is_official)             AS official_comments,
            count(DISTINCT link_id)                         AS social_links,
            count(DISTINCT public_name)                     AS publics,
            count(DISTINCT org_name)                        AS organizations,
            count(DISTINCT author)                          AS unique_authors,
            min(d)                                          AS first_comment,
            max(d)                                          AS last_comment,
            round(extract(epoch FROM (max(d)-min(d)))/86400.0) AS span_days
     FROM base
     """),

    ("02_monthly",
     "динамика потока по месяцам — растёт ли объём, есть ли сезонность",
     """
     SELECT date_trunc('month', d)::date                AS month,
            count(*)                                    AS comments,
            count(*) FILTER (WHERE is_appeal)           AS appeals,
            count(*) FILTER (WHERE is_official)         AS official_comments,
            count(DISTINCT author)                      AS unique_authors,
            count(DISTINCT link_id)                     AS active_links
     FROM base WHERE d IS NOT NULL
     GROUP BY 1 ORDER BY 1
     """),

    ("03_message_types",
     "доля реальных обращений в потоке — проверка тезиса «25 из 100»",
     """
     SELECT coalesce(nullif(mtype,''),'(не размечено)')  AS message_type,
            count(*)                                     AS cnt,
            round(100.0*count(*)/nullif(sum(count(*)) OVER (),0), 1) AS pct
     FROM base WHERE analyzed
     GROUP BY 1 ORDER BY cnt DESC
     """),

    ("04_response_rate",
     "ГЛАВНОЕ: какая доля обращений осталась без ответа организации",
     """
     SELECT count(*)                                            AS appeals,
            count(*) FILTER (WHERE reply_date IS NOT NULL)      AS answered,
            round(100.0*count(*) FILTER (WHERE reply_date IS NOT NULL)
                  / nullif(count(*),0), 1)                      AS answer_rate_pct,
            round(avg(reply_hours)::numeric, 1)                 AS avg_reply_hours,
            round(percentile_cont(0.5) WITHIN GROUP (ORDER BY reply_hours)::numeric, 1) AS median_reply_hours,
            round(percentile_cont(0.9) WITHIN GROUP (ORDER BY reply_hours)::numeric, 1) AS p90_reply_hours,
            -- пороги совпадают с SLA «Инцидент-менеджмента»: 4 ч (важное) / 8 ч (обычное)
            count(*) FILTER (WHERE reply_hours <= 4)                         AS answered_le_4h,
            count(*) FILTER (WHERE reply_hours > 4   AND reply_hours <= 8)   AS answered_4_8h,
            count(*) FILTER (WHERE reply_hours > 8   AND reply_hours <= 24)  AS answered_8_24h,
            count(*) FILTER (WHERE reply_hours > 24  AND reply_hours <= 72)  AS answered_1_3d,
            count(*) FILTER (WHERE reply_hours > 72  AND reply_hours <= 168) AS answered_3_7d,
            count(*) FILTER (WHERE reply_hours > 168)                        AS answered_gt_7d
     FROM appeals
     """),

    ("04b_sla_by_month",
     "отвечаемость по месяцам против SLA Инцидента (4ч/8ч) — динамика, а не средняя по больнице",
     """
     SELECT date_trunc('month', d)::date                                     AS month,
            count(*)                                                         AS appeals,
            count(*) FILTER (WHERE reply_date IS NOT NULL)                   AS answered,
            round(100.0*count(*) FILTER (WHERE reply_hours <= 8)
                  /nullif(count(*),0), 1)                                    AS pct_within_8h,
            round(percentile_cont(0.5) WITHIN GROUP (ORDER BY reply_hours)::numeric,1) AS median_reply_hours
     FROM appeals WHERE d IS NOT NULL
     GROUP BY 1 ORDER BY 1
     """),

    ("05_by_public",
     "разброс между площадками: где обращений много, а ответов нет",
     """
     SELECT b.public_name, b.network, b.org_name,
            count(*)                                       AS comments,
            count(*) FILTER (WHERE b.is_appeal)            AS appeals,
            round(100.0*count(*) FILTER (WHERE b.is_appeal)/nullif(count(*),0),1) AS appeal_share_pct,
            min(b.d)                                       AS first_comment,
            max(b.d)                                       AS last_comment
     FROM base b
     GROUP BY 1,2,3 ORDER BY appeals DESC
     """),

    ("06_response_by_public",
     "рейтинг площадок по отвечаемости — есть ли реальный разброс",
     """
     SELECT public_name, org_name,
            count(*)                                            AS appeals,
            count(*) FILTER (WHERE reply_date IS NOT NULL)       AS answered,
            round(100.0*count(*) FILTER (WHERE reply_date IS NOT NULL)
                  /nullif(count(*),0),1)                         AS answer_rate_pct,
            round(percentile_cont(0.5) WITHIN GROUP (ORDER BY reply_hours)::numeric,1) AS median_reply_hours
     FROM appeals
     GROUP BY 1,2 HAVING count(*) >= 5 ORDER BY answer_rate_pct ASC
     """),

    ("07_categories",
     "структура обращений по темам и отвечаемость внутри каждой темы",
     """
     SELECT coalesce(nullif(category,''),'(без категории)')     AS category,
            count(*)                                            AS appeals,
            round(100.0*count(*)/nullif(sum(count(*)) OVER (),0),1) AS pct_of_appeals,
            count(*) FILTER (WHERE reply_date IS NOT NULL)       AS answered,
            round(100.0*count(*) FILTER (WHERE reply_date IS NOT NULL)
                  /nullif(count(*),0),1)                         AS answer_rate_pct,
            count(DISTINCT nullif(case_name,''))                 AS distinct_cases
     FROM appeals
     GROUP BY 1 ORDER BY appeals DESC
     """),

    ("08_top_cases",
     "конкретные адресные проблемы: сколько раз поднимали и как долго живут",
     """
     SELECT nullif(case_name,'')                                 AS case_name,
            coalesce(nullif(category,''),'(без категории)')      AS category,
            count(*)                                             AS mentions,
            count(DISTINCT author)                               AS distinct_authors,
            count(*) FILTER (WHERE reply_date IS NOT NULL)       AS answered,
            min(d)                                               AS first_seen,
            max(d)                                               AS last_seen,
            round(extract(epoch FROM (max(d)-min(d)))/86400.0)   AS lifespan_days
     FROM appeals WHERE nullif(case_name,'') IS NOT NULL
     GROUP BY 1,2 ORDER BY mentions DESC LIMIT 200
     """),

    ("09_repeat_distribution",
     "системность: сколько проблем разовые, а сколько повторяются",
     """
     SELECT CASE WHEN mentions = 1 THEN '1 упоминание'
                 WHEN mentions BETWEEN 2 AND 3  THEN '2-3'
                 WHEN mentions BETWEEN 4 AND 10 THEN '4-10'
                 WHEN mentions BETWEEN 11 AND 30 THEN '11-30'
                 ELSE '31+' END                    AS bucket,
            count(*)                               AS cases,
            sum(mentions)                          AS total_mentions
     FROM (
        SELECT nullif(case_name,'') AS case_name, count(*) AS mentions
        FROM appeals WHERE nullif(case_name,'') IS NOT NULL GROUP BY 1
     ) c GROUP BY 1 ORDER BY min(mentions)
     """),

    ("10_daily_by_category",
     "ряд для поиска всплесков: были ли дни, когда тема взрывалась",
     """
     SELECT d::date                                          AS day,
            coalesce(nullif(category,''),'(без категории)')  AS category,
            count(*)                                         AS appeals
     FROM appeals WHERE d IS NOT NULL
     GROUP BY 1,2 HAVING count(*) > 0 ORDER BY 1,3 DESC
     """),

    ("11_author_repeat",
     "кто пишет: разовые жители или узкая группа активистов",
     """
     SELECT CASE WHEN n = 1 THEN '1 обращение'
                 WHEN n BETWEEN 2 AND 3 THEN '2-3'
                 WHEN n BETWEEN 4 AND 10 THEN '4-10'
                 ELSE '11+' END       AS bucket,
            count(*)                  AS authors,
            sum(n)                    AS appeals
     FROM (
        SELECT author, count(*) AS n FROM base
        WHERE is_appeal AND author IS NOT NULL GROUP BY 1
     ) a GROUP BY 1 ORDER BY min(n)
     """),

    ("12_throughput",
     "фактическая производительность обработки по дням",
     """
     SELECT analyzed_at::date            AS day,
            coalesce(model_version,'—')  AS model_version,
            count(*)                     AS analyzed
     FROM base WHERE analyzed_at IS NOT NULL
     GROUP BY 1,2 ORDER BY 1
     """),

    ("13_sentiment",
     "тональность потока по месяцам — фон настроения",
     """
     SELECT date_trunc('month', d)::date         AS month,
            coalesce(sentiment,'(нет)')          AS sentiment,
            count(*)                             AS cnt
     FROM base WHERE analyzed AND d IS NOT NULL
     GROUP BY 1,2 ORDER BY 1,3 DESC
     """),
]


async def probe_schema(conn) -> bool:
    """True — есть новые колонки comment_analysis, можно считать по полной."""
    rows = await conn.fetch("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'comment_analysis'
    """)
    cols = {r["column_name"] for r in rows}
    need = {"message_type", "hierarchy", "is_official_response", "classification_state"}
    missing = need - cols
    if missing:
        print(f"  ! в comment_analysis нет колонок: {', '.join(sorted(missing))}")
        print("    -> считаю по урезанной схеме (часть цифр будет недоступна)")
        return False
    return True


def write_csv(path: Path, rows) -> int:
    if not rows:
        path.write_text("", encoding="utf-8-sig")
        return 0
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(list(rows[0].keys()))
        for r in rows:
            w.writerow(["" if v is None else v for v in r.values()])
    return len(rows)


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dsn", help="postgresql://user:pass@host:port/db")
    ap.add_argument("--label", help="имя папки для выгрузки (по умолчанию — имя БД)")
    ap.add_argument("--out", help="куда класть CSV", default=None)
    args = ap.parse_args()

    dsn, label = build_dsn(args)
    outdir = Path(args.out) if args.out else (ROOT / "data" / "db_export" / label)
    outdir.mkdir(parents=True, exist_ok=True)

    safe = dsn.split("@")[-1]
    print(f"Подключаюсь: ...@{safe}")
    conn = await asyncpg.connect(dsn)
    try:
        full = await probe_schema(conn)
        base = BASE_FULL if full else BASE_LEGACY
        errors: list[str] = []
        manifest: list[tuple[str, str, int]] = []

        for name, purpose, sql in QUERIES:
            try:
                rows = await conn.fetch(base + sql)
                n = write_csv(outdir / f"{name}.csv", rows)
                manifest.append((name, purpose, n))
                print(f"  ok  {name:<24} {n:>7} строк   — {purpose}")
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{name}: {type(exc).__name__}: {exc}")
                print(f"  FAIL {name}: {exc}")

        with (outdir / "_manifest.csv").open("w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f, delimiter=";")
            w.writerow(["file", "что доказывает", "строк"])
            w.writerows([(f"{n}.csv", p, c) for n, p, c in manifest])
            w.writerow(["_schema", "полная схема comment_analysis" if full else "УРЕЗАННАЯ схема", ""])

        if errors:
            (outdir / "_errors.txt").write_text("\n".join(errors), encoding="utf-8")
            print(f"\nОшибок: {len(errors)} — см. _errors.txt")
    finally:
        await conn.close()

    print(f"\nГотово: {outdir}")


if __name__ == "__main__":
    asyncio.run(main())
