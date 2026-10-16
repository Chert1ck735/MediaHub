"""Собирает актуальный набор расхождений LLM vs gold для ревью-сервиса.

Источник — свежий data/eval/eval_labeled.jsonl (пиши его через `python -m tools.eval_report`).
Категорийные расхождения, попадающие в accept-лист, не считаются ошибкой.
Результат — data/eval/gold_review.json (схема под tools/gold_review_server.py).

Запуск:  python -m tools.build_gold_review
"""
from __future__ import annotations

import json
from pathlib import Path

EVAL = Path("data/eval")


def _accept() -> dict[str, set[str]]:
    acc: dict[str, set[str]] = {}
    p = EVAL / "category_accept.jsonl"
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                acc[r["comment_id"]] = set(r.get("accept") or [])
    return acc


def main() -> None:
    rows = [json.loads(l) for l in (EVAL / "eval_labeled.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    acc = _accept()
    out = []
    for r in rows:
        cid = r["comment_id"]
        g_pain, l_pain = int(r["gold_is_pain"]), int(r["llm_is_pain"])
        g_cat, l_cat = r.get("gold_category") or "", r.get("llm_category") or ""
        allow = acc.get(cid, set())
        if g_pain == 0 and l_pain == 1:
            typ, reason = "LLM=боль, голд=нет", f"LLM пометил болью ({l_cat or '—'}), в голде — не боль"
        elif g_pain == 1 and l_pain == 0:
            typ, reason = "голд=боль, LLM=нет", "LLM пропустил боль, размеченную в голде"
        elif g_pain == 1 and l_pain == 1 and l_cat != g_cat and l_cat not in allow:
            typ, reason = "категория расходится", f"LLM: {l_cat or '—'} · голд: {g_cat or '—'}"
        else:
            continue
        out.append({
            "n": 0, "comment_id": cid, "public": r.get("public") or "",
            "text": (r.get("text") or "")[:600], "type": typ,
            "gold_is_pain": g_pain, "gold_category": g_cat,
            "llm_is_pain": l_pain, "llm_category": l_cat,
            "accept": ", ".join(sorted(allow)),
            "prop_is_pain": g_pain, "prop_category": g_cat, "reason": reason,
        })
    order = {"LLM=боль, голд=нет": 0, "категория расходится": 1, "голд=боль, LLM=нет": 2}
    out.sort(key=lambda x: order[x["type"]])
    for i, r in enumerate(out, 1):
        r["n"] = i
    (EVAL / "gold_review.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    from collections import Counter
    print(f"расхождений: {len(out)} | {dict(Counter(r['type'] for r in out))}")


if __name__ == "__main__":
    main()
