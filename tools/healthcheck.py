"""Smoke-test основных API endpoint'ов.

Запуск:
    python tools/healthcheck.py
    python tools/healthcheck.py --host https://prod.example.com

Создаёт JWT по JWT_SECRET из .env и дёргает критичные endpoint'ы.
В CI/CD-цепочке: запустить перед деплоем — если падает, не катить.
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

# bootstrap: путь к корню проекта
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from dotenv import load_dotenv
load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

try:
    from jose import jwt as pyjwt
except ImportError:
    print("ERROR: python-jose not installed. Run: pip install python-jose[cryptography]")
    sys.exit(2)


def fail(msg: str) -> None:
    print(f"  FAIL: {msg}")


def ok(msg: str) -> None:
    print(f"  OK: {msg}")


def make_token(secret: str, user_id: str, email: str) -> str:
    return pyjwt.encode(
        {"sub": user_id, "email": email, "exp": datetime.now(timezone.utc) + timedelta(hours=1)},
        secret, algorithm="HS256",
    )


def request_json(host: str, path: str, token: str, *, method: str = "GET", body=None):
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Authorization": f"Bearer {token}"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(f"{host}{path}", method=method, data=data, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            payload = json.loads(r.read().decode("utf-8") or "null")
            return r.status, payload, None
    except urllib.error.HTTPError as e:
        return e.code, None, e.read().decode("utf-8", errors="replace")[:300]
    except Exception as e:
        return None, None, f"{type(e).__name__}: {e}"


def pick_user_from_db():
    """Берём из БД первого user'а для теста — без жёсткой привязки к UUID."""
    import psycopg2
    conn = psycopg2.connect(
        host=os.getenv("DB_HOST"), port=os.getenv("DB_PORT"),
        user=os.getenv("DB_USER"), password=os.getenv("DB_PASS"),
        dbname=os.getenv("DB_NAME"),
    )
    cur = conn.cursor()
    cur.execute("select id, email from users order by created_at asc limit 1")
    row = cur.fetchone()
    cur.close(); conn.close()
    if not row:
        return None, None
    return str(row[0]), row[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="http://localhost:8000")
    args = parser.parse_args()

    secret = os.getenv("JWT_SECRET", "")
    if not secret or secret in {"DEV_ONLY_SET_JWT_SECRET_IN_ENV", "change-me-in-production-secret-key-32chars"}:
        print("ERROR: JWT_SECRET не задан или дефолтный. Проверь .env")
        sys.exit(2)

    user_id, email = pick_user_from_db()
    if not user_id:
        print("ERROR: в БД нет ни одного user'а. Создай через /api/auth/register")
        sys.exit(2)
    token = make_token(secret, user_id, email)

    print(f"healthcheck {args.host} (as {email})")
    failures: list[str] = []

    # --- 1. open endpoint (без auth) — /docs возвращает HTML, не JSON,
    # поэтому проверяем напрямую через urllib без json-парсинга.
    print("\n[1] GET /docs (открытый, html)")
    try:
        with urllib.request.urlopen(f"{args.host}/docs", timeout=10) as r:
            if r.status == 200:
                ok("docs available")
            else:
                fail(f"status={r.status}")
                failures.append("docs")
    except Exception as e:
        fail(f"{type(e).__name__}: {e}")
        failures.append("docs")

    # --- 2. analytics summary (требует auth) ---
    print("\n[2] GET /api/analytics/summary?period=all")
    status, data, err = request_json(args.host, "/api/analytics/summary?period=all", token)
    if status == 200 and isinstance(data, dict) and "pain_count" in data:
        ok(f"pain_count={data['pain_count']}, relevant={data['relevant_comment_count']}, unclassified={data.get('unclassified_count')}, window={data.get('recommended_post_window')!r}")
    elif status == 404:
        ok("404 — нет snapshot в БД, это допустимо для пустой системы")
    else:
        fail(f"status={status}, err={err}")
        failures.append("summary")

    # --- 3. analytics pains ---
    print("\n[3] GET /api/analytics/pains?period=all")
    status, data, err = request_json(args.host, "/api/analytics/pains?period=all", token)
    if status == 200 and isinstance(data, list):
        ok(f"pains={len(data)}")
        if data:
            p = data[0]
            tc = len(p.get("top_cases") or [])
            ok(f"  first pain {p.get('title')!r}: sev={p.get('severity_level')}, top_cases={tc}, mentions={p.get('mentions_count')}")
    else:
        fail(f"status={status}, err={err}")
        failures.append("pains")

    # --- 4. pain detail (с Reaction Gap) ---
    if status == 200 and isinstance(data, list) and data:
        pid = data[0]["id"]
        print(f"\n[4] GET /api/analytics/pains/{pid[:8]}...")
        st2, det, e2 = request_json(args.host, f"/api/analytics/pains/{pid}", token)
        if st2 == 200 and isinstance(det, dict):
            rg = det.get("reaction_gap")
            rg_str = "no" if not rg or rg.get("measured_events", 0) == 0 else f"avg={rg.get('avg_gap_pct')}% by {rg['measured_events']}"
            ok(f"detail loaded, subproblems={len(det.get('subproblem_items', []))}, reaction_gap={rg_str}")
        else:
            fail(f"status={st2}, err={e2}")
            failures.append("pain_detail")

    # --- 5. events list ---
    print("\n[5] GET /api/events/")
    status, data, err = request_json(args.host, "/api/events/", token)
    if status == 200 and isinstance(data, list):
        ok(f"events={len(data)}")
    else:
        fail(f"status={status}, err={err}")
        failures.append("events")

    # --- 6. calendar list ---
    print("\n[6] GET /api/calendar/")
    status, data, err = request_json(args.host, "/api/calendar/", token)
    if status == 200 and isinstance(data, list):
        ok(f"calendar={len(data)}")
    else:
        fail(f"status={status}, err={err}")
        failures.append("calendar")

    # --- 7. publics ---
    print("\n[7] GET /api/analytics/publics")
    status, data, err = request_json(args.host, "/api/analytics/publics", token)
    if status == 200 and isinstance(data, list):
        ok(f"publics={len(data)}")
    else:
        fail(f"status={status}, err={err}")
        failures.append("publics")

    # --- 8. pain trends (sparkline data) ---
    print("\n[8] GET /api/analytics/pains/trends?weeks=12")
    status, data, err = request_json(args.host, "/api/analytics/pains/trends?weeks=12", token)
    if status == 200 and isinstance(data, list):
        ok(f"trends={len(data)} pains")
    else:
        fail(f"status={status}, err={err}")
        failures.append("trends")

    # --- 9. negative tests: без токена endpoints должны давать 401 ---
    print("\n[9] negative tests (без auth → должно быть 401)")
    for path in ("/api/analytics/summary", "/api/analytics/pains", "/api/events/", "/api/calendar/"):
        st, _, _ = request_json(args.host, path, token="")
        if st == 401:
            ok(f"401 on {path}")
        else:
            fail(f"{path} вернул {st} вместо 401 — endpoint открыт!")
            failures.append(f"open:{path}")

    # --- 10. JWT_SECRET default check (отдельный сценарий) ---
    print("\n[10] sanity: текущий JWT_SECRET — не дефолт")
    if len(secret) >= 32 and secret not in {"DEV_ONLY_SET_JWT_SECRET_IN_ENV", "change-me-in-production-secret-key-32chars"}:
        ok(f"JWT_SECRET длина={len(secret)}, не дефолтный")
    else:
        fail(f"JWT_SECRET выглядит дефолтным (len={len(secret)})")
        failures.append("jwt_secret")

    print()
    if failures:
        print(f"HEALTHCHECK FAILED: {len(failures)} проверок — {failures}")
        sys.exit(1)
    print("HEALTHCHECK OK: все проверки прошли.")


if __name__ == "__main__":
    main()
