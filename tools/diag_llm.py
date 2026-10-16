"""Диагностика: почему очередь классификации не движется.

Запуск из корня: python -m tools.diag_llm
Проверяет пробу здоровья LLM (по ней воркер решает работать или стоять),
реальный вызов классификации и состояние очереди в БД.
"""
import asyncio
import time

from sqlalchemy import text

from backend.app.config import settings
from backend.db.database import async_session_maker
from backend.modules.analytics import llm_health


async def main() -> None:
    provider = (getattr(settings, "LLM_PROVIDER", "openai") or "openai").lower()
    base = (
        getattr(settings, "OLLAMA_URL", "")
        if provider == "ollama"
        else getattr(settings, "OPENAI_COMPATIBLE_BASE_URL", "")
    )
    print(f"провайдер: {provider}; base: {base}")

    started = time.monotonic()
    ok = llm_health._probe(5.0)
    print(f"проба здоровья (по ней воркер работает/стоит): {'ДОСТУПЕН' if ok else 'НЕДОСТУПЕН'} "
          f"за {time.monotonic() - started:.1f}s")

    print("пробный вызов классификации…")
    started = time.monotonic()
    try:
        from backend.modules.llm import service as llm_service
        payload = await llm_service.analyze_comment("Когда почините дорогу на Ленина 5? Одни ямы!")
        keys = list(payload.keys()) if isinstance(payload, dict) else type(payload).__name__
        print(f"  ОТВЕТИЛ за {time.monotonic() - started:.1f}s, ключи: {keys}")
    except Exception as exc:
        print(f"  УПАЛ за {time.monotonic() - started:.1f}s: {type(exc).__name__}: {exc}")

    async with async_session_maker() as db:
        rows = (await db.execute(text("""
            SELECT classification_state,
                   count(*),
                   count(*) FILTER (WHERE next_attempt_at IS NOT NULL AND next_attempt_at <= now()) AS due,
                   count(*) FILTER (WHERE next_attempt_at > now()) AS later,
                   min(created_at), max(updated_at)
            FROM comment_analysis
            GROUP BY 1 ORDER BY 2 DESC
        """))).all()
        print("\nочередь (state | всего | ретрай созрел | ретрай позже | старейший created | свежайший updated):")
        for r in rows:
            print(f"  {r[0]:11} {r[1]:>7} {r[2]:>6} {r[3]:>6}  {str(r[4])[:19]}  {str(r[5])[:19]}")

        recent = (await db.execute(text("""
            SELECT count(*) FROM comment_analysis
            WHERE classification_state = 'done' AND updated_at >= now() - interval '15 minutes'
        """))).scalar()
        print(f"\nразобрано за последние 15 минут: {recent}")
        print("если 0 при доступном LLM — смотреть лог бэкенда: строки "
              "'LLM unreachable — classification worker idling' (воркер стоит по пробе) "
              "или 'Worker batch: picked=' (воркер работает).")


asyncio.run(main())
