"""HTML-просмотрщик размеченного эталона (читать в браузере, не в Excel).

Делает data/eval/eval_view.html: таблица с текстом, эталоном (gold), решением
LLM и rule-классификатора, с подсветкой расхождений и кнопками-фильтрами.
Статус считается по LLM, если был прогон classify_eval_llm, иначе по rule.

Запуск:  python -m tools.eval_view   (после eval_report)
"""
from __future__ import annotations

import html
import json
from pathlib import Path

EVAL_DIR = Path("data/eval")


def _status(r, pain_key, cat_key):
    gold = str(r.get("gold_is_pain")) == "1"
    pred = bool(r.get(pain_key))
    if pred and not gold:
        return "fp", "ЛОЖНАЯ боль"
    if gold and not pred:
        return "fn", "ПРОПУЩЕНА боль"
    if gold and pred:
        gc = (r.get("gold_category") or "").strip()
        pc = (r.get(cat_key) or "").strip()
        if gc and gc != pc:
            return "catmiss", "категория мимо"
        return "ok", "боль ок"
    return "tn", "не боль ок"


def main() -> None:
    rows = [json.loads(l) for l in (EVAL_DIR / "eval_labeled.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    has_llm = any("llm_is_pain" in r for r in rows)
    pain_key, cat_key = ("llm_is_pain", "llm_category") if has_llm else ("rule_is_pain", "rule_category")
    engine = "LLM" if has_llm else "rule"

    cells = []
    counts = {"fp": 0, "fn": 0, "catmiss": 0, "ok": 0, "tn": 0}
    for i, r in enumerate(rows, 1):
        st, label = _status(r, pain_key, cat_key)
        counts[st] += 1
        g_pain = "боль" if str(r.get("gold_is_pain")) == "1" else "—"
        l_pain = "боль" if r.get("llm_is_pain") else "—"
        r_pain = "боль" if r.get("rule_is_pain") else "—"
        llm_cell = (f'<td>{l_pain}<br><b>{html.escape(r.get("llm_category","") or "")}</b>'
                    f'<br><span class="sub">{html.escape(r.get("llm_subcategory","") or "")}</span>'
                    f'<br><span class="case">{html.escape(r.get("llm_case","") or "")}</span></td>'
                    if has_llm else "")
        cells.append(
            f'<tr class="{st}" data-st="{st}">'
            f'<td>{i}</td>'
            f'<td class="pub">{html.escape(r.get("public",""))}</td>'
            f'<td class="txt">{html.escape(r.get("text","")[:600])}</td>'
            f'<td>{g_pain}<br><b>{html.escape(r.get("gold_category",""))}</b>'
            f'<br><span class="sub">{html.escape(r.get("gold_subcategory","") or "")}</span>'
            f'<br><span class="case">{html.escape(r.get("gold_case","") or "")}</span>'
            f'<br><i>{html.escape(r.get("gold_noise",""))}</i></td>'
            f'{llm_cell}'
            f'<td>{r_pain}<br><b>{html.escape(r.get("rule_category","") or "")}</b></td>'
            f'<td class="st">{label}</td></tr>'
        )
    summary = (f"Движок статуса: {engine} · всего {len(rows)} · ложных болей {counts['fp']} · "
               f"пропущено {counts['fn']} · категория мимо {counts['catmiss']} · "
               f"боль ок {counts['ok']} · не-боль ок {counts['tn']}")
    llm_th = "<th>LLM</th>" if has_llm else ""
    doc = f"""<!doctype html><html lang="ru"><head><meta charset="utf-8">
<title>Эталон классификации</title><style>
body{{font-family:system-ui,Arial;margin:16px;font-size:14px}}
table{{border-collapse:collapse;width:100%}}
th,td{{border:1px solid #ccc;padding:6px;vertical-align:top;text-align:left}}
th{{position:sticky;top:0;background:#222;color:#fff}}
.txt{{max-width:620px}} .pub{{white-space:nowrap;color:#555;font-size:12px}}
.fp{{background:#ffe0e0}} .fn{{background:#fff0d0}} .catmiss{{background:#fffbcc}} .ok{{background:#e6f6e6}} .tn{{background:#fff}}
.st{{white-space:nowrap;font-weight:bold;font-size:12px}}
.sub{{color:#06c;font-size:12px}} .case{{color:#888;font-size:11px}}
#bar{{position:sticky;top:0;background:#fff;padding:8px 0}}
button{{margin-right:6px;padding:6px 10px;cursor:pointer}}
</style></head><body>
<h2>Эталон vs {engine}-классификатор</h2>
<p>{summary}</p>
<div id="bar">
<button onclick="flt('all')">Все</button>
<button onclick="flt('fp')">Ложные боли</button>
<button onclick="flt('fn')">Пропущенные</button>
<button onclick="flt('catmiss')">Категория мимо</button>
<button onclick="flt('ok')">Боль ок</button>
</div>
<table><thead><tr><th>#</th><th>Паблик</th><th>Текст</th><th>Эталон</th>{llm_th}<th>Rule</th><th>Статус</th></tr></thead>
<tbody>{''.join(cells)}</tbody></table>
<script>
function flt(s){{document.querySelectorAll('tbody tr').forEach(t=>{{
 t.style.display=(s==='all'||t.dataset.st===s)?'':'none';}});}}
</script></body></html>"""
    out = EVAL_DIR / "eval_view.html"
    out.write_text(doc, encoding="utf-8")
    print(f"{summary}\nОткрой в браузере: {out.resolve()}")


if __name__ == "__main__":
    main()
