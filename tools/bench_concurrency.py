"""Замер пропускной способности LLM при разной параллельности.

Гоняет comments через classify_eval_llm в bench-режиме (не трогает llm_pred.jsonl,
не зовёт отчёт). Каждый уровень повторяется и берётся МЕДИАНА — иначе на общем
сервере один прогон даёт пляшущие цифры.

АВТО-МАСШТАБ: число комментов на замер растёт с параллельностью (мало на низкой,
больше на высокой). Так каждая ячейка идёт примерно одинаковое время (~2-3 мин),
и высокая параллель успевает пройти разогрев (иначе throughput завышается).

Плато на таблице = реальный потолок (число слотов сервера, --parallel).
Где прирост между соседними <~10% — там потолок.

Запуск (когда доступна LLM):  python -m tools.bench_concurrency
Параметры через env:
  BENCH_LEVELS=1,2,4,8,12,16,24   какие параллельности мерить
  BENCH_PER_SLOT=6                комментов на единицу параллельности (limit = clamp(PER_SLOT*c, 20, 150))
  BENCH_REPEATS=2                 повторов на уровень (берётся медиана)
"""
from __future__ import annotations

import os
import re
import subprocess
import sys

LEVELS = [int(x) for x in os.getenv("BENCH_LEVELS", "1,2,4,8,12,16,24").split(",")]
PER_SLOT = int(os.getenv("BENCH_PER_SLOT", "6"))
REPEATS = int(os.getenv("BENCH_REPEATS", "2"))


def _limit_for(c: int) -> int:
    return max(20, min(150, PER_SLOT * c))


def _median(xs):
    xs = sorted(xs)
    n = len(xs)
    if not n:
        return None
    return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2


def _one(c, limit):
    # PYTHONIOENCODING — иначе на Windows дочерний процесс пишет в cp1251,
    # а мы читаем как utf-8 и падаем на первой русской букве.
    env = dict(os.environ, EVAL_LLM_BENCH="1", EVAL_LLM_LIMIT=str(limit),
               EVAL_LLM_CONCURRENCY=str(c), PYTHONIOENCODING="utf-8")
    out = subprocess.run([sys.executable, "-m", "tools.classify_eval_llm"],
                         env=env, capture_output=True, text=True,
                         encoding="utf-8", errors="replace")
    m = re.search(r"\[bench\].*?([\d.]+) комментов/мин.*?avg ([\d.]+)с p95 ([\d.]+)с", out.stdout or "")
    if not m:
        tail = (out.stdout or out.stderr or "").strip().splitlines()[-3:]
        print(f"    не распарсил; хвост: {tail}")
        return None
    return float(m.group(1)), float(m.group(2)), float(m.group(3))


def main() -> None:
    print(f"Уровни {LEVELS}, повторов {REPEATS}, лимит = {PER_SLOT}×параллель (20..150 комментов)\n", flush=True)
    rows = []
    for c in LEVELS:
        limit = _limit_for(c)
        rates, avgs, p95s = [], [], []
        for i in range(REPEATS):
            print(f">>> параллельность {c}, повтор {i+1}/{REPEATS} ({limit} комментов)…", flush=True)
            r = _one(c, limit)
            if r:
                rates.append(r[0]); avgs.append(r[1]); p95s.append(r[2])
                print(f"    {r[0]:.1f}/мин  avg {r[1]:.1f}с  p95 {r[2]:.1f}с")
        rows.append((c, _median(rates), _median(avgs), _median(p95s)))

    print("\n=== СВОДКА (медиана по повторам): параллельность → throughput / задержка")
    print(f"{'парал':>6} {'комм/мин':>10} {'avg с':>8} {'p95 с':>8} {'прирост':>9}")
    prev = None
    for c, rate, avg, p95 in rows:
        if rate is None:
            print(f"{c:>6} {'нет данных':>10}")
            continue
        gain = "" if prev is None else f"{(rate/prev-1)*100:+.0f}%"
        print(f"{c:>6} {rate:>10.1f} {avg:>8.1f} {p95:>8.1f} {gain:>9}")
        prev = rate

    valid = [(c, r) for c, r, *_ in rows if r]
    if len(valid) >= 2:
        knee = valid[0]
        for (c0, r0), (c1, r1) in zip(valid, valid[1:]):
            if r1 / r0 - 1 < 0.10:  # прирост <10% — дальше плато
                knee = (c0, r0)
                break
            knee = (c1, r1)
        print(f"\nРабочая точка ~{knee[0]} ({knee[1]:.0f}/мин): дальше прирост <10%. "
              f"Выше — растёт задержка на коммент, throughput почти не меняется.")
        print("Точный потолок = с каким --parallel запущен llama.cpp на сервере (спроси у хоста).")


if __name__ == "__main__":
    main()
