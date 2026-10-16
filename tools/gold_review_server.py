"""Мини-сервис ревью голда: страница с кнопками «Боль/Не боль» + категория.

Показывает расхождения LLM vs gold (data/eval/gold_review.json) с моими
предложениями. Решения сохраняются в data/eval/corrections.jsonl (оверрайд
поверх голда, обратимо). Без внешних зависимостей.

Запуск:  python -m tools.gold_review_server   → http://localhost:8765
"""
from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

EVAL = Path("data/eval")
REVIEW = EVAL / "gold_review.json"
CORR = EVAL / "corrections.jsonl"
PORT = 8765

CATEGORIES = [
    "ЖКХ и городская среда", "Дороги и транспорт", "Экология и санитарное состояние",
    "Социальная сфера", "Управление и обратная связь", "Безопасность и ЧС",
    "Экономика, торговля и регулирование", "Связь и цифровая инфраструктура", "Другое",
]


def _rows() -> list[dict]:
    return json.loads(REVIEW.read_text(encoding="utf-8"))


def _save(decisions: list[dict]) -> int:
    """Пишет в corrections.jsonl только те строки, где решение != текущего голда."""
    rows = {r["comment_id"]: r for r in _rows()}
    existing = {}
    if CORR.exists():
        for line in CORR.read_text(encoding="utf-8").splitlines():
            if line.strip():
                c = json.loads(line)
                existing[c["comment_id"]] = c
    changed = 0
    for d in decisions:
        cid = d["comment_id"]
        row = rows.get(cid)
        if not row:
            continue
        is_pain = int(d["is_pain"])
        cat = (d.get("category") or "").strip() if is_pain else ""
        if is_pain == row["gold_is_pain"] and cat == (row["gold_category"] or ""):
            existing.pop(cid, None)  # решение == голд → правка не нужна
            continue
        existing[cid] = {
            "comment_id": cid, "gold_is_pain": str(is_pain),
            "gold_category": cat, "_why": "review",
        }
        changed += 1
    with CORR.open("w", encoding="utf-8") as f:
        for c in existing.values():
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    return changed


PAGE = """<!doctype html><html lang=ru><meta charset=utf-8>
<title>Ревью голда</title>
<style>
body{font-family:system-ui,Arial;max-width:900px;margin:0 auto;padding:16px;background:#0f1218;color:#e6e6e6}
.bar{position:sticky;top:0;background:#0f1218;padding:10px 0;border-bottom:1px solid #333;display:flex;gap:12px;align-items:center;z-index:5}
.card{border:1px solid #2a2f3a;border-radius:10px;padding:12px;margin:10px 0;background:#161a22}
.meta{font-size:12px;color:#8a93a5;margin:4px 0}
.text{margin:6px 0;line-height:1.4}
.reason{font-size:12px;color:#c9a86a;margin:4px 0}
button{cursor:pointer;border:1px solid #3a4150;background:#222836;color:#e6e6e6;border-radius:8px;padding:6px 12px;font-size:14px}
button.on-pain{background:#7a2e2e;border-color:#a04040}
button.on-not{background:#2e5a7a;border-color:#4080a0}
select{background:#222836;color:#e6e6e6;border:1px solid #3a4150;border-radius:8px;padding:6px}
.changed{outline:2px solid #c9a86a}
.save{background:#2e7a45;border-color:#40a060;font-weight:600;padding:8px 16px}
.chip{font-size:11px;padding:2px 6px;border-radius:6px;background:#222836;color:#8a93a5}
</style>
<div class=bar>
  <button class=save onclick=save()>💾 Сохранить в corrections</button>
  <span id=status></span>
  <span style="margin-left:auto" class=chip>клик «Боль/Не боль», категория ниже</span>
</div>
<div id=list></div>
<script>
const CATS=__CATS__;
let ROWS=__ROWS__;
const state={}; // cid -> {is_pain, category}
for(const r of ROWS) state[r.comment_id]={is_pain:r.prop_is_pain, category:r.prop_category};

function esc(s){return (s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;')}
function render(){
  const el=document.getElementById('list'); el.innerHTML='';
  for(const r of ROWS){
    const s=state[r.comment_id];
    const changed = (s.is_pain!==r.gold_is_pain) || (s.is_pain===1 && (s.category||'')!==(r.gold_category||''));
    const d=document.createElement('div'); d.className='card'+(changed?' changed':'');
    d.innerHTML=`
      <div class=meta>#${r.n} · ${esc(r.type)} · ${esc(r.public)}</div>
      <div class=text>«${esc(r.text)}»</div>
      <div class=meta>голд: ${r.gold_is_pain?'боль':'не боль'}${r.gold_category?' / '+esc(r.gold_category):''}
        &nbsp;|&nbsp; LLM: ${r.llm_is_pain?'боль':'не боль'}${r.llm_category?' / '+esc(r.llm_category):''}
        ${r.accept?'&nbsp;|&nbsp; accept: '+esc(r.accept):''}</div>
      <div class=reason>предложение: ${esc(r.reason)}</div>
      <div style="display:flex;gap:8px;align-items:center;margin-top:6px">
        <button class="${s.is_pain?'on-pain':''}" onclick="setp('${r.comment_id}',1)">Боль</button>
        <button class="${s.is_pain?'':'on-not'}" onclick="setp('${r.comment_id}',0)">Не боль</button>
        <select onchange="setc('${r.comment_id}',this.value)" ${s.is_pain?'':'disabled'}>
          <option value=''>— категория —</option>
          ${CATS.map(c=>`<option ${c===s.category?'selected':''}>${esc(c)}</option>`).join('')}
        </select>
      </div>`;
    el.appendChild(d);
  }
  const ch=ROWS.filter(r=>{const s=state[r.comment_id];return (s.is_pain!==r.gold_is_pain)||(s.is_pain===1&&(s.category||'')!==(r.gold_category||''))}).length;
  document.getElementById('status').textContent=`изменений к голду: ${ch}`;
}
function setp(cid,v){state[cid].is_pain=v; if(!v)state[cid].category=''; render()}
function setc(cid,v){state[cid].category=v; render()}
async function save(){
  const dec=ROWS.map(r=>({comment_id:r.comment_id, is_pain:state[r.comment_id].is_pain, category:state[r.comment_id].category}));
  const res=await fetch('/save',{method:'POST',body:JSON.stringify(dec)});
  const j=await res.json();
  document.getElementById('status').textContent=`сохранено правок: ${j.changed} (в corrections.jsonl)`;
}
render();
</script></html>"""


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):  # тихо
        pass

    def do_GET(self):
        if self.path not in ("/", "/index.html"):
            self.send_error(404); return
        html = (PAGE
                .replace("__CATS__", json.dumps(CATEGORIES, ensure_ascii=False))
                .replace("__ROWS__", json.dumps(_rows(), ensure_ascii=False).replace("</", "<\\/")))
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path != "/save":
            self.send_error(404); return
        n = int(self.headers.get("Content-Length", 0))
        decisions = json.loads(self.rfile.read(n) or b"[]")
        changed = _save(decisions)
        body = json.dumps({"changed": changed}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    print(f"Ревью голда: http://localhost:{PORT}  (Ctrl+C — стоп)")
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
