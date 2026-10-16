"""Прогон эталонных комментов через LLM-путь классификатора.

Запускать КОГДА ДОСТУПНА LLM (адрес в .env OPENAI_COMPATIBLE_BASE_URL).
Классифицирует 694 эталонных коммента через llm_service.analyze_comment,
пишет предсказания ИНКРЕМЕНТАЛЬНО в data/eval/llm_pred.jsonl (партиал не теряется
при обрыве), в конце сам печатает метрики LLM против эталона.

Запуск:  python -m tools.classify_eval_llm
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path

from backend.app.config import settings
from backend.modules.analytics.utils.category_classifier import normalize_hierarchy_values
from backend.modules.llm import service as llm_service

EVAL_DIR = Path("data/eval")
PRED_PATH = EVAL_DIR / "llm_pred.jsonl"
PER_COMMENT_TIMEOUT = 120
CONCURRENCY = int(os.getenv("EVAL_LLM_CONCURRENCY", "8"))
LIMIT = int(os.getenv("EVAL_LLM_LIMIT", "0"))  # >0 — прогнать только N комментов (bench параллельности)
BENCH = os.getenv("EVAL_LLM_BENCH", "") == "1"  # bench-режим: не трогать llm_pred.jsonl и не звать отчёт


def _comments():
    seen = {}
    for fn in ("eval_set.jsonl", "augment.jsonl"):
        p = EVAL_DIR / fn
        if not p.exists():
            continue
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                seen[r["comment_id"]] = r["text"]
    return list(seen.items())


async def _classify(text: str):
    payload = await llm_service.analyze_comment(text)
    cat, sub, case = normalize_hierarchy_values(
        category=str(getattr(payload.hierarchy, "category", "") or ""),
        subcategory=str(getattr(payload.hierarchy, "subcategory", "") or ""),
        case_name=str(getattr(payload.hierarchy, "case", "") or ""),
        source_text=text,
    )
    irrelevant = (
        getattr(payload, "is_official_response", False)
        or getattr(payload, "author_type", "") in {"admin", "official"}
        or getattr(payload, "message_type", "") == "offtopic"
        or getattr(payload, "relevance", "") == "irrelevant"
    )
    is_pain = (not irrelevant) and getattr(payload, "message_type", "") in {"complaint", "request"} and bool(cat)
    return {
        "llm_relevance": "irrelevant" if irrelevant else "relevant",
        "llm_msg_type": getattr(payload, "message_type", ""),
        "llm_category": "" if irrelevant else cat,
        "llm_subcategory": "" if irrelevant else sub,
        "llm_case": "" if irrelevant else case,
        "llm_is_pain": int(is_pain),
    }


async def _preflight() -> str | None:
    try:
        await asyncio.wait_for(llm_service.analyze_comment("проверка связи"), timeout=25)
        return None
    except asyncio.TimeoutError:
        return "LLM не ответила за 25с"
    except Exception as exc:
        return str(exc)[:160]


async def main() -> None:
    prov = getattr(settings, "LLM_PROVIDER", "?")
    url = (getattr(settings, "OPENAI_COMPATIBLE_BASE_URL", "") if prov == "openai"
           else getattr(settings, "OLLAMA_URL", ""))
    print(f"LLM_PROVIDER={prov}  url={url}\nПроверяю доступность LLM…", flush=True)
    err = await _preflight()
    if err:
        print(f"\nLLM НЕДОСТУПНА: {err}\n  Проверь адрес в .env и доступность сети. Прогон отменён.")
        return
    print("LLM отвечает, начинаю прогон\n", flush=True)

    items = _comments()
    if LIMIT > 0:
        items = items[:LIMIT]
    total = len(items)
    sem = asyncio.Semaphore(max(1, CONCURRENCY))
    done = errors = 0
    durations: list[float] = []
    results: list[dict] = []
    lock = asyncio.Lock()
    partial = PRED_PATH.with_suffix(".partial")  # прерывание не затрёт прошлый полный прогон
    partial.write_text("", encoding="utf-8")
    t0 = time.perf_counter()
    last_print = [t0]
    print(f"Параллельность={CONCURRENCY}, комментов={total}\n", flush=True)

    async def work(cid, text):
        nonlocal done, errors
        async with sem:
            t = time.perf_counter()
            try:
                res = await asyncio.wait_for(_classify(text), timeout=PER_COMMENT_TIMEOUT)
            except Exception as exc:
                res = {"llm_error": str(exc)[:120], "llm_is_pain": "", "llm_category": ""}
                errors += 1
            dt = time.perf_counter() - t
        res["comment_id"] = cid
        res["llm_seconds"] = round(dt, 2)
        async with lock:
            durations.append(dt)
            results.append(res)
            with partial.open("a", encoding="utf-8") as f:  # инкрементально
                f.write(json.dumps(res, ensure_ascii=False) + "\n")
            done += 1
            now = time.perf_counter()
            if done == total or now - last_print[0] >= 15:  # по времени — видно, что живой
                last_print[0] = now
                rate = done / (now - t0) * 60
                print(f"  {done}/{total}  ошибок:{errors}  ~{rate:.0f}/мин  посл.коммент {dt:.1f}с", flush=True)

    await asyncio.gather(*[work(cid, text) for cid, text in items])
    if not BENCH:
        partial.replace(PRED_PATH)  # полный прогон готов — заменяем основной файл
    elapsed = time.perf_counter() - t0
    ok_durs = sorted(durations)
    avg = sum(ok_durs) / len(ok_durs) if ok_durs else 0
    p50 = ok_durs[len(ok_durs)//2] if ok_durs else 0
    p95 = ok_durs[int(len(ok_durs)*0.95)] if ok_durs else 0
    print(f"\nГотово: {len(results)} классифицировано, ошибок LLM: {errors}")
    print(f"  предсказания: {PRED_PATH}")
    print(f"\n=== СКОРОСТЬ (LLM-классификация) при параллельности {CONCURRENCY}")
    print(f"  всего: {elapsed:.0f}с на {total} комментов  →  {total/elapsed*60:.0f} комментов/мин")
    print(f"  на 1 коммент: среднее {avg:.1f}с · медиана {p50:.1f}с · p95 {p95:.1f}с")

    if BENCH:
        print(f"\n[bench] параллельность {CONCURRENCY}: {total/elapsed*60:.1f} комментов/мин "
              f"avg {avg:.1f}с p95 {p95:.1f}с (llm_pred.jsonl и отчёт не трогаю)")
        return

    print("\n" + "=" * 50)
    try:
        from tools.eval_report import main as report_main
        report_main()
    except Exception as exc:
        print(f"(отчёт не собрался автоматически: {exc}); запусти: python -m tools.eval_report")


if __name__ == "__main__":
    asyncio.run(main())
