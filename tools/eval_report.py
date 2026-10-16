"""Отчёт качества классификации: эталон (gold-разметка) против классификатора.

Сливает eval_set.jsonl (реалистичная выборка) + augment.jsonl (добор болей) с
разметкой gold_*.jsonl. Метрики:
  - precision / доля ложных болей — на РЕАЛИСТИЧНОЙ подвыборке (subset=representative),
    т.к. там естественное соотношение шума;
  - recall и точность категории — на ВСЁМ наборе (там больше болей);
  - sys (текущее решение в БД) против gold — где система классифицировала.
Пишет data/eval/eval_labeled.jsonl и .csv (открыть в Excel и смотреть глазами).

Запуск:  python -m tools.eval_report
"""
from __future__ import annotations

import csv
import glob
import json
from collections import Counter
from pathlib import Path

from backend.modules.analytics.utils.case_extractor import (
    case_location_key,
    case_lookup_text,
)
from tools.eval_rules import classify_rule

EVAL_DIR = Path("data/eval")


def _case_hit(pred: str, gold: str) -> bool:
    """Кейс совпал: по нормализованной локации, иначе по нормализованному тексту."""
    gk, pk = case_location_key(gold), case_location_key(pred)
    if gk and pk:
        return gk == pk
    return bool(pred) and case_lookup_text(pred) == case_lookup_text(gold)


def _load_accept():
    """comment_id -> множество допустимых категорий (gold + защитимые альтернативы)."""
    acc = {}
    p = EVAL_DIR / "category_accept.jsonl"
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                acc[r["comment_id"]] = set(r.get("accept") or [])
    return acc


def _stems(text: str) -> set:
    """Грубые основы слов (для open-vocab подкатегорий: газификация≈газоснабжение)."""
    import re
    out = set()
    for w in re.findall(r"[а-яёa-z0-9]+", (text or "").lower()):
        if len(w) >= 4 and w not in {"программа", "очередь", "вопрос", "проблема", "город", "район"}:
            out.add(w[:5])
    return out


def _sub_soft_hit(pred: str, gold: str) -> bool:
    """Подкатегория совпала по смыслу: точное совпадение или пересечение основ слов."""
    pl, gl = (pred or "").strip().lower(), (gold or "").strip().lower()
    if pl and pl == gl:
        return True
    return bool(_stems(pred) & _stems(gold))


def _load():
    base = {}
    for fname, subset in (("eval_set.jsonl", "representative"), ("augment.jsonl", "augment")):
        p = EVAL_DIR / fname
        if not p.exists():
            continue
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                r.setdefault("subset", subset)
                base[r["comment_id"]] = r
    for gf in glob.glob(str(EVAL_DIR / "parts" / "gold_*.jsonl")):
        for line in Path(gf).read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            g = json.loads(line)
            cid = g.get("comment_id")
            if cid in base:
                base[cid].update({k: v for k, v in g.items() if k.startswith("gold_")})
    corr = EVAL_DIR / "corrections.jsonl"
    if corr.exists():
        for line in corr.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            c = json.loads(line)
            r = base.get(c.get("comment_id"))
            if r:
                r.update({k: v for k, v in c.items() if k.startswith("gold_")})
    return [r for r in base.values() if str(r.get("gold_is_pain", "")) in ("0", "1")]


def _prf(tp, fp, fn):
    p = tp / (tp + fp) if (tp + fp) else 0.0
    r = tp / (tp + fn) if (tp + fn) else 0.0
    return p, r


def main() -> None:
    rows = _load()
    for r in rows:
        r["rule_is_pain"], r["rule_category"] = classify_rule(r["text"], r.get("author_external_id"))

    llm_path = EVAL_DIR / "llm_pred.jsonl"
    if llm_path.exists():
        lp = {}
        for line in llm_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                p = json.loads(line)
                lp[p["comment_id"]] = p
        for r in rows:
            p = lp.get(r["comment_id"])
            if p:
                r["llm_is_pain"] = bool(p.get("llm_is_pain"))
                r["llm_category"] = p.get("llm_category", "")
                r["llm_subcategory"] = p.get("llm_subcategory", "")
                r["llm_case"] = p.get("llm_case", "")

    # экспорт для просмотра глазами
    cols = ["public", "subset", "text", "gold_is_pain", "gold_category", "gold_subcategory",
            "gold_case", "gold_noise", "gold_notes", "rule_is_pain", "rule_category",
            "sys_relevance", "sys_category", "sys_source", "comment_id"]
    with (EVAL_DIR / "eval_labeled.jsonl").open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with (EVAL_DIR / "eval_labeled.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)

    rep = [r for r in rows if r.get("subset") == "representative"]
    pains = sum(1 for r in rows if str(r["gold_is_pain"]) == "1")
    print(f"=== Эталон: {len(rows)} комментов (реалист. {len(rep)} + добор {len(rows)-len(rep)}), болей={pains}")
    print("шум в реалист. выборке:", dict(Counter(r.get("gold_noise", "") for r in rep if str(r["gold_is_pain"]) != "1")))

    # precision / ложные боли — на реалистичной выборке
    tp = fp = 0
    fp_ex = []
    for r in rep:
        gold = str(r["gold_is_pain"]) == "1"
        if r["rule_is_pain"] and gold:
            tp += 1
        elif r["rule_is_pain"] and not gold:
            fp += 1
            if len(fp_ex) < 10:
                fp_ex.append((r["rule_category"], r.get("gold_noise", ""), r["text"][:65]))
    print(f"\n=== RULE-путь, PRECISION на реалистичной выборке ({len(rep)})")
    print(f"precision={tp/(tp+fp) if (tp+fp) else 0:.0%}  доля ложных болей={fp/(tp+fp) if (tp+fp) else 0:.0%}  (TP={tp} FP={fp})")

    # recall + категория — на всём наборе
    r_tp = r_fn = 0
    cat_hit = cat_tot = 0
    cat_miss = []
    for r in rows:
        gold = str(r["gold_is_pain"]) == "1"
        if not gold:
            continue
        if r["rule_is_pain"]:
            r_tp += 1
            gc = (r.get("gold_category") or "").strip()
            if gc:
                cat_tot += 1
                if r["rule_category"] == gc:
                    cat_hit += 1
                elif len(cat_miss) < 10:
                    cat_miss.append((r["rule_category"], gc, r["text"][:60]))
        else:
            r_fn += 1
    print(f"\n=== RULE-путь, RECALL и КАТЕГОРИЯ на всём наборе (болей={r_tp+r_fn})")
    print(f"recall={r_tp/(r_tp+r_fn) if (r_tp+r_fn) else 0:.0%}  (поймал {r_tp}, пропустил {r_fn})")
    print(f"категория верна: {cat_hit}/{cat_tot}" + (f" ({cat_hit/cat_tot:.0%})" if cat_tot else ""))

    if fp_ex:
        print("\nЛОЖНЫЕ БОЛИ (rule выдумал боль, эталон — не боль):")
        for pc, noise, t in fp_ex:
            print(f"  [{pc or '—'}|{noise}] {t}")
    if cat_miss:
        print("\nМИСКЛАСС категории (rule → gold):")
        for pc, gc, t in cat_miss:
            print(f"  {pc!r} → {gc!r}: {t}")

    # sys на классифицированных
    classified = [r for r in rows if (r.get("sys_source") or "") not in ("", "unknown")]
    if classified:
        s_tp = s_fp = s_fn = 0
        for r in classified:
            gold = str(r["gold_is_pain"]) == "1"
            sys_pain = (r.get("sys_relevance") == "relevant") and bool((r.get("sys_category") or "").strip())
            if sys_pain and gold: s_tp += 1
            elif sys_pain and not gold: s_fp += 1
            elif not sys_pain and gold: s_fn += 1
        sp, sr = _prf(s_tp, s_fp, s_fn)
        print(f"\n=== SYS (в БД) против эталона — {len(classified)} классифиц. (из них LLM мало!)")
        print(f"precision={sp:.0%} recall={sr:.0%} ложных={s_fp/(s_tp+s_fp) if (s_tp+s_fp) else 0:.0%}")

    # LLM-путь (если был прогон classify_eval_llm)
    if any("llm_is_pain" in r for r in rows):
        scored = [r for r in rows if "llm_is_pain" in r]
        scored_rep = [r for r in scored if r.get("subset") == "representative"]
        l_tp = sum(1 for r in scored_rep if r["llm_is_pain"] and str(r["gold_is_pain"]) == "1")
        l_fp = sum(1 for r in scored_rep if r["llm_is_pain"] and str(r["gold_is_pain"]) != "1")
        accept = _load_accept()
        rc_tp = rc_fn = lc_hit = lc_tot = lc_acc = 0
        sub_hit = sub_soft = sub_tot = case_hit = case_tot = 0
        for r in scored:
            if str(r["gold_is_pain"]) != "1":
                continue
            if r["llm_is_pain"]:
                rc_tp += 1
                gc = (r.get("gold_category") or "").strip()
                lcat = (r.get("llm_category") or "").strip()
                if gc:
                    lc_tot += 1
                    lc_hit += int(lcat == gc)
                    ok_set = accept.get(r["comment_id"]) or {gc}
                    lc_acc += int(lcat in ok_set)
                gsub = (r.get("gold_subcategory") or "").strip()
                if gsub:
                    sub_tot += 1
                    lsub = (r.get("llm_subcategory") or "").strip()
                    sub_hit += int(lsub.lower() == gsub.lower())
                    sub_soft += int(_sub_soft_hit(lsub, gsub))
                gcase = (r.get("gold_case") or "").strip()
                if gcase:
                    case_tot += 1
                    case_hit += int(_case_hit((r.get("llm_case") or "").strip(), gcase))
            else:
                rc_fn += 1
        print(f"\n=== LLM-путь против эталона ({len(scored)} прогнано)")
        print(f"precision={l_tp/(l_tp+l_fp) if (l_tp+l_fp) else 0:.0%} (реалист.)  "
              f"recall={rc_tp/(rc_tp+rc_fn) if (rc_tp+rc_fn) else 0:.0%}")
        print(f"категория строго={lc_hit}/{lc_tot}" + (f" ({lc_hit/lc_tot:.0%})" if lc_tot else "")
              + f"  с учётом допустимых={lc_acc}/{lc_tot}" + (f" ({lc_acc/lc_tot:.0%})" if lc_tot else "")
              + "  (допустимые = gold + защитимые альтернативы из аудита)")
        print(f"подкатегория строго={sub_hit}/{sub_tot}" + (f" ({sub_hit/sub_tot:.0%})" if sub_tot else "")
              + f"  мягко={sub_soft}/{sub_tot}" + (f" ({sub_soft/sub_tot:.0%})" if sub_tot else "")
              + f"  кейс={case_hit}/{case_tot}" + (f" ({case_hit/case_tot:.0%})" if case_tot else "")
              + "  (на верно пойманных болях, где есть gold-метка)")

    try:
        from tools.eval_view import main as view_main
        view_main()
    except Exception as exc:
        print(f"(вьюшка не собралась: {exc}); запусти: python -m tools.eval_view")
    print(f"\nГлазами смотреть: {EVAL_DIR/'eval_view.html'} (браузер) или eval_labeled.csv")


if __name__ == "__main__":
    main()
