"""Покомментное сравнение двух прогонов LLM против голда.

Запуск:  python -m tools.compare_runs [файл_A] [файл_B]
По умолчанию A=llm_pred.14b.jsonl (старый), B=llm_pred.jsonl (новый).

Печатает метрики обоих прогонов и разбор расхождений: что новый прогон
починил, что сломал, где разошлись категории. Ни БД, ни LLM не нужны.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

EVAL_DIR = Path("data/eval")
EXAMPLES = 12


def _read_jsonl(path: Path):
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            out.append(json.loads(line))
    return out


def _gold():
    gold = {}
    for p in sorted((EVAL_DIR / "parts").glob("gold_*.jsonl")):
        for r in _read_jsonl(p):
            gold[r["comment_id"]] = dict(r)
    for r in _read_jsonl(EVAL_DIR / "corrections.jsonl"):
        cid = r["comment_id"]
        if cid in gold:
            gold[cid].update({k: v for k, v in r.items() if not k.startswith("_")})
    for r in gold.values():
        r["gold_is_pain"] = int(str(r.get("gold_is_pain", 0)) or 0)
    return gold


def _accept():
    acc = {}
    for r in _read_jsonl(EVAL_DIR / "category_accept.jsonl"):
        acc[r["comment_id"]] = set(r.get("accept") or [])
    return acc


def _texts():
    out = {}
    for fn in ("eval_set.jsonl", "augment.jsonl"):
        for r in _read_jsonl(EVAL_DIR / fn):
            out[r["comment_id"]] = r.get("text", "")
    return out


def _preds(path: Path):
    return {r["comment_id"]: r for r in _read_jsonl(path)}


def _cat_ok(pred, g, accept):
    """accept-aware: категория верна, если совпала с голдом или входит в допустимые."""
    c = (pred.get("llm_category") or "").strip()
    if not c:
        return False
    if c == (g.get("gold_category") or "").strip():
        return True
    return c in accept.get(g["comment_id"], set())


def _metrics(preds, gold, accept):
    tp = fp = fn = 0
    cat_ok = cat_total = 0
    for cid, g in gold.items():
        p = preds.get(cid)
        if p is None:
            continue
        pred_pain = int(p.get("llm_is_pain", 0))
        if pred_pain and g["gold_is_pain"]:
            tp += 1
            cat_total += 1
            if _cat_ok(p, g, accept):
                cat_ok += 1
        elif pred_pain and not g["gold_is_pain"]:
            fp += 1
        elif not pred_pain and g["gold_is_pain"]:
            fn += 1
    prec = tp / (tp + fp) * 100 if tp + fp else 0.0
    rec = tp / (tp + fn) * 100 if tp + fn else 0.0
    cat = cat_ok / cat_total * 100 if cat_total else 0.0
    return {"P": prec, "R": rec, "cat": cat, "tp": tp, "fp": fp, "fn": fn, "n": sum(1 for c in gold if c in preds)}


def _short(text, n=110):
    t = " ".join((text or "").split())
    return t[:n] + ("…" if len(t) > n else "")


def main():
    a_path = EVAL_DIR / (sys.argv[1] if len(sys.argv) > 1 else "llm_pred.14b.jsonl")
    b_path = EVAL_DIR / (sys.argv[2] if len(sys.argv) > 2 else "llm_pred.jsonl")
    gold, accept, texts = _gold(), _accept(), _texts()
    A, B = _preds(a_path), _preds(b_path)
    if not A or not B:
        print(f"нет данных: A={a_path} ({len(A)}), B={b_path} ({len(B)})")
        return

    ma, mb = _metrics(A, gold, accept), _metrics(B, gold, accept)
    print(f"A = {a_path.name}  ({ma['n']} комментов)")
    print(f"B = {b_path.name}  ({mb['n']} комментов)")
    print()
    print(f"{'':10} {'A':>8} {'B':>8} {'Δ':>8}")
    for k in ("P", "R", "cat"):
        print(f"{k:10} {ma[k]:8.1f} {mb[k]:8.1f} {mb[k] - ma[k]:+8.1f}")
    print(f"{'TP/FP/FN':10} {ma['tp']}/{ma['fp']}/{ma['fn']:<4} {mb['tp']}/{mb['fp']}/{mb['fn']}")

    common = [c for c in gold if c in A and c in B]
    fixed_fn, broke_tp, fixed_fp, new_fp, cat_fix, cat_broke = [], [], [], [], [], []
    for cid in common:
        g = gold[cid]
        a, b = A[cid], B[cid]
        pa, pb = int(a.get("llm_is_pain", 0)), int(b.get("llm_is_pain", 0))
        if pa != pb:
            if g["gold_is_pain"]:
                (fixed_fn if pb else broke_tp).append(cid)
            else:
                (fixed_fp if not pb else new_fp).append(cid)
        elif pa and pb and g["gold_is_pain"]:
            oa, ob = _cat_ok(a, g, accept), _cat_ok(b, g, accept)
            if oa != ob:
                (cat_fix if ob else cat_broke).append(cid)

    print()
    print("B против A:")
    print(f"  нашёл потерянные боли (FN→TP): {len(fixed_fn)}")
    print(f"  потерял найденные боли (TP→FN): {len(broke_tp)}")
    print(f"  убрал ложные боли (FP→TN):     {len(fixed_fp)}")
    print(f"  добавил ложные боли (TN→FP):   {len(new_fp)}")
    print(f"  починил категорию:             {len(cat_fix)}")
    print(f"  сломал категорию:              {len(cat_broke)}")

    for title, ids in (
        ("ПОТЕРЯЛ БОЛИ (было верно у A, стало FN у B)", broke_tp),
        ("НОВЫЕ ЛОЖНЫЕ БОЛИ у B", new_fp),
        ("НАШЁЛ ДОПОЛНИТЕЛЬНО (FN у A → TP у B)", fixed_fn),
        ("СЛОМАЛ КАТЕГОРИЮ", cat_broke),
    ):
        if not ids:
            continue
        print()
        print(f"--- {title} ---")
        for cid in ids[:EXAMPLES]:
            g, b = gold[cid], B[cid]
            print(f"  [{cid[:8]}] {_short(texts.get(cid))}")
            print(
                f"      голд: pain={g['gold_is_pain']} cat={g.get('gold_category') or '-'}"
                f" | B: pain={b.get('llm_is_pain')} type={b.get('llm_msg_type')} cat={b.get('llm_category') or '-'}"
            )
        if len(ids) > EXAMPLES:
            print(f"  … ещё {len(ids) - EXAMPLES}")

    out = EVAL_DIR / "_compare_runs.json"
    out.write_text(
        json.dumps(
            {
                "a": a_path.name, "b": b_path.name, "metrics_a": ma, "metrics_b": mb,
                "fixed_fn": fixed_fn, "broke_tp": broke_tp, "fixed_fp": fixed_fp,
                "new_fp": new_fp, "cat_fix": cat_fix, "cat_broke": cat_broke,
            },
            ensure_ascii=False, indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\nполный список расхождений: {out}")


if __name__ == "__main__":
    main()
