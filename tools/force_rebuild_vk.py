"""Принудительная пересборка VK-снапшота БЕЗ LLM (force_reclassify=False).

Нужна, когда меняется логика сборки снапшота (исключение комментов-сообществ,
дедуп адресных кейсов и т.п.), но новых комментариев нет — тогда обычное
«Сформировать» на UI видит needs_rebuild=false и снапшот не пересобирает.
Этот скрипт пересобирает напрямую: переклассификации LLM не делает, только
заново бакетирует уже размеченные комментарии под текущий код.

Использование:
    python tools/force_rebuild_vk.py --email belkovskyy@yandex.ru
    python tools/force_rebuild_vk.py            # берёт первого пользователя
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import select

from backend.db.database import async_session_maker
from backend.db.users import User
from backend.modules.analytics import service


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--email", default=None)
    args = ap.parse_args()

    async with async_session_maker() as db:
        q = select(User)
        if args.email:
            q = q.where(User.email == args.email)
        user = (await db.execute(q.limit(1))).scalar_one_or_none()
        if user is None:
            print("Пользователь не найден")
            return
        print(f"Пересборка для user={user.email} org={user.organization_id} (без LLM)…")
        snapshot, stats = await service.rebuild_vk_comment_snapshot(
            db, user, force_reclassify=False, progress=None
        )
        pain_count = await service.count_snapshot_pains(db, str(snapshot.id))
        print(f"Готово. snapshot={snapshot.id}  болей={pain_count}")
        print(f"  reclassified={stats.get('reclassified_comments')}  "
              f"llm={stats.get('llm_classified_comments')}  "
              f"fallback={stats.get('fallback_classified_comments')}")


if __name__ == "__main__":
    asyncio.run(main())
