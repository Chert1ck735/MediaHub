"""Сводка LLM-нагрузки сервиса из generated_reports/llm_usage_metrics.jsonl.

Разбивает запросы по usage_context (comment_analysis / analytics_prefilter / …):
сколько запросов, успех/ошибки, латентность (avg/p95), запросов в минуту и пик GPU.
Показывает, кто и сколько ест на LLM-сервере.

Запуск:        python -m tools.llm_load_report
За период:     python -m tools.llm_load_report --hours 2
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

METRICS = Path("generated_reports/llm_usage_metrics.jsonl")


def _p95(xs: list[float]) -> float:
    if not xs:
        return 0.0
    s = sorted(xs)
    return s[min(len(s) - 1, int(len(s) * 0.95))]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=float, default=0, help=">0 — только за последние N часов")
    args = ap.parse_args()

    if not METRICS.exists():
        print(f"Нет файла метрик: {METRICS}")
        return

    cutoff = None
    if args.hours > 0:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=args.hours)

    by_ctx: dict[str, dict] = defaultdict(
        lambda: {"n": 0, "ok": 0, "fail": 0, "durs": [], "gpu": [], "tmin": None, "tmax": None}
    )
    for line in METRICS.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            r = json.loads(line)
        except Exception:
            continue
        ts = None
        try:
            ts = datetime.fromisoformat(str(r.get("timestamp")))
        except Exception:
            pass
        if cutoff and (ts is None or ts < cutoff):
            continue
        c = by_ctx[str(r.get("usage_context") or "?")]
        c["n"] += 1
        if r.get("success"):
            c["ok"] += 1
            d = r.get("duration_seconds")
            if isinstance(d, (int, float)):
                c["durs"].append(float(d))
        else:
            c["fail"] += 1
        g = (r.get("gpu") or {}).get("peak_utilization_percent")
        if isinstance(g, (int, float)):
            c["gpu"].append(float(g))
        if ts:
            c["tmin"] = ts if c["tmin"] is None else min(c["tmin"], ts)
            c["tmax"] = ts if c["tmax"] is None else max(c["tmax"], ts)

    if not by_ctx:
        print("Нет записей за выбранный период.")
        return

    print(f"{'usage_context':<22}{'запр':>7}{'ok':>7}{'fail':>6}{'avg с':>8}{'p95 с':>8}{'зап/мин':>9}{'GPU%avg':>9}")
    print("-" * 76)
    for ctx, c in sorted(by_ctx.items(), key=lambda kv: kv[1]["n"], reverse=True):
        durs = c["durs"]
        avg = sum(durs) / len(durs) if durs else 0.0
        span_min = ((c["tmax"] - c["tmin"]).total_seconds() / 60) if (c["tmin"] and c["tmax"]) else 0
        rpm = c["n"] / span_min if span_min > 0 else 0
        gpu = sum(c["gpu"]) / len(c["gpu"]) if c["gpu"] else 0
        print(
            f"{ctx:<22}{c['n']:>7}{c['ok']:>7}{c['fail']:>6}{avg:>8.1f}{_p95(durs):>8.1f}{rpm:>9.1f}{gpu:>9.0f}"
        )


if __name__ == "__main__":
    main()
