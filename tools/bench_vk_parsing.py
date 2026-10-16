"""Бенчмарк парсинга комментариев VK."""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time

# Чтобы скрипт работал как `python tools/bench_vk_parsing.py` из корня репо:
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.app.config import settings
from backend.modules.vk.utils.api_client import VkApiClient
from backend.modules.vk.utils.errors import VkApiError


def _resolve_owner(client: VkApiClient, owner_arg: str | None, domain_arg: str | None) -> int:
    # По короткому имени паблика (--domain digitalkrsk24) разрешаем owner_id.
    name = domain_arg
    if name is None and owner_arg is not None:
        try:
            return int(owner_arg)  # числовой owner_id
        except ValueError:
            name = owner_arg  # это короткое имя
    if name is not None:
        res = client.resolve_screen_name(name) or {}
        obj_id = res.get("object_id")
        if not obj_id:
            raise SystemExit(f"Не удалось разрешить '{name}'")
        # сообщество → owner_id отрицательный, профиль → положительный
        return -int(obj_id) if res.get("type") in {"group", "page", "event"} else int(obj_id)
    if settings.GROUP_ID:
        return -abs(settings.GROUP_ID)
    raise SystemExit("Укажите --owner <id|имя>, --domain <имя> или задайте GROUP_ID в .env")


async def _run_level(
    client: VkApiClient,
    owner_id: int,
    post_ids: list[int],
    concurrency: int,
) -> tuple[float, int, int]:
    """Возвращает (время_сек, всего_комментов, ошибок) для одного уровня."""
    sem = asyncio.Semaphore(max(1, concurrency))
    totals = {"comments": 0, "errors": 0}

    async def _one(post_id: int) -> None:
        async with sem:
            try:
                comments = await asyncio.to_thread(
                    client.fetch_all_comments, owner_id, post_id, max_comments=500
                )
                totals["comments"] += len(comments)
            except VkApiError:
                totals["errors"] += 1

    t0 = time.perf_counter()
    await asyncio.gather(*[_one(p) for p in post_ids])
    return time.perf_counter() - t0, totals["comments"], totals["errors"]


async def main() -> None:
    parser = argparse.ArgumentParser(description="VK comment-parsing benchmark")
    parser.add_argument("--owner", default=None, help="owner_id (отрицательный для сообщества) или короткое имя")
    parser.add_argument("--domain", default=None, help="короткое имя паблика, напр. digitalkrsk24")
    parser.add_argument("--posts", type=int, default=30, help="сколько постов взять со стены")
    parser.add_argument("--levels", default="1,5,15", help="уровни concurrency через запятую")
    args = parser.parse_args()

    client = VkApiClient()
    owner_id = _resolve_owner(client, args.owner, args.domain)
    levels = [int(x) for x in args.levels.split(",") if x.strip()]

    print(f"owner_id={owner_id}  delay={settings.VK_INTER_REQUEST_DELAY}s  max_posts={args.posts}")

    posts = await asyncio.to_thread(
        client.fetch_all_wall, owner_id=owner_id, max_posts=args.posts
    )
    counts = [(p.get("comments") or {}).get("count", 0) for p in posts]
    post_ids = [int(p["id"]) for p, c in zip(posts, counts) if c > 0]
    print(f"постов всего: {len(posts)}, из них с комментариями: {len(post_ids)}")
    if counts:
        print(f"comments.count по постам: max={max(counts)} sum={sum(counts)} | первые 15: {counts[:15]}")
    if not post_ids:
        print("Нет постов с комментариями — нечего мерить.")
        print("Если везде 0 — вероятно, комментарии на постах отключены или закрыты для токена.")
        return

    print()
    print(f"{'concurrency':>11} | {'время, с':>9} | {'комментов':>10} | {'ошибок':>7}")
    print("-" * 46)
    for level in levels:
        elapsed, comments, errors = await _run_level(client, owner_id, post_ids, level)
        print(f"{level:>11} | {elapsed:>9.1f} | {comments:>10} | {errors:>7}")

    print()
    print("Подсказка: время должно падать с ростом concurrency. Если в колонке")
    print("«ошибок» >0 — снизь concurrency или подними VK_INTER_REQUEST_DELAY в .env.")


if __name__ == "__main__":
    asyncio.run(main())
