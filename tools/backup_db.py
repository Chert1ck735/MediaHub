"""pg_dump БД (cross-platform: Windows/Linux/macOS).

Альтернатива backup_db.bat для случаев, когда pg_dump есть, но bat-скрипты
неудобны (Linux deploy, CI). Использует те же DB_* из .env.

Запуск:
    python tools/backup_db.py
    python tools/backup_db.py --out custom/path.sql
"""
import argparse
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=None, help="Путь к .sql файлу. По умолчанию backups/<db>_<ts>.sql")
    parser.add_argument("--keep", type=int, default=10, help="Сколько последних бэкапов хранить (старее — удаляются)")
    args = parser.parse_args()

    db_name = (os.getenv("DB_NAME") or "").strip()
    db_user = (os.getenv("DB_USER") or "").strip()
    db_host = (os.getenv("DB_HOST") or "localhost").strip()
    db_port = (os.getenv("DB_PORT") or "5432").strip()
    db_pass = (os.getenv("DB_PASS") or "").strip()
    if not db_name or not db_user:
        print("ERROR: DB_NAME/DB_USER не заданы в .env")
        return 1

    if shutil.which("pg_dump") is None:
        print("ERROR: pg_dump не найден в PATH. Установи PostgreSQL client tools.")
        return 1

    backup_dir = PROJECT_ROOT / "backups"
    backup_dir.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    out_path = Path(args.out) if args.out else backup_dir / f"{db_name}_{ts}.sql"

    env = os.environ.copy()
    env["PGPASSWORD"] = db_pass

    print(f"Backing up {db_name}@{db_host}:{db_port} -> {out_path}")
    rc = subprocess.call(
        [
            "pg_dump",
            "-h", db_host, "-p", db_port,
            "-U", db_user, "-d", db_name,
            "-f", str(out_path),
            "--no-owner", "--no-acl",
        ],
        env=env,
    )
    if rc != 0:
        print(f"pg_dump exited with code {rc}")
        return rc

    size = out_path.stat().st_size
    print(f"Done. Size: {size:,} bytes")

    # Ротация: оставляем последние N
    if args.keep > 0:
        files = sorted(backup_dir.glob(f"{db_name}_*.sql"), key=lambda p: p.stat().st_mtime, reverse=True)
        for old in files[args.keep:]:
            print(f"Removing old backup: {old.name}")
            old.unlink()

    return 0


if __name__ == "__main__":
    sys.exit(main())
