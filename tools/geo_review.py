"""Страница ручной разметки геокодинга: один HTML-файл, который открывают в браузере.

Собирает страницу из файлов `tools/geo_label`, снятых разными провайдерами.
Ответы, указывающие на одно место, схлопываются в одного кандидата — размечать
приходится место, а не провайдера. Так один заход закрывает все провайдеры
сразу, а не по кругу для каждого.

Кандидат показывается независимо от того, принял его наш фильтр или отверг.
Вердикт «верно» у отвергнутого кандидата и есть мера того, что мы выбрасываем
зря; вердикт «неверно» у принятого — мера ошибок на карте.

    python -m tools.geo_review yandex.xlsx 2gis.xlsx dadata.xlsx --serve
    # разметили в браузере → verdicts.csv
    python -m tools.geo_compare yandex.xlsx 2gis.xlsx --verdicts verdicts.csv

Файл самодостаточный, его можно переслать разметчику. Но Chrome запрещает
открытым с диска страницам сохранять прогресс, поэтому надёжнее `--serve`:
страница поднимается на localhost, а вердикты пишутся в CSV сами.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from tools.geo_eval import distance_km
from tools.geo_label import STATUS_FOUND, _read

VERDICTS = ("верно", "неверно", "не адрес")

# Ответы ближе этого считаем одним и тем же местом.
SAME_PLACE_KM = 0.3

TEMPLATE = r"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Разметка геокодинга</title>
<style>
  :root {
    --bg:#f6f7f9; --card:#fff; --line:#dfe3e8; --text:#1c2024;
    --muted:#6b7280; --accent:#2f6feb; --ok:#1a7f37; --bad:#b42318; --warn:#a15c07;
  }
  @media (prefers-color-scheme: dark) {
    :root { --bg:#16181d; --card:#1f2228; --line:#31353d; --text:#e8eaed;
            --muted:#9aa0a6; --accent:#5b8def; --ok:#4ac26b; --bad:#f97066; --warn:#e3a008; }
  }
  * { box-sizing:border-box; }
  body { margin:0; background:var(--bg); color:var(--text);
         font:15px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; }
  header { position:sticky; top:0; z-index:5; background:var(--card);
           border-bottom:1px solid var(--line); padding:10px 16px; }
  .head { display:flex; gap:16px; align-items:baseline; flex-wrap:wrap; }
  .head b { font-size:16px; }
  .muted { color:var(--muted); font-size:13px; }
  .bar { height:6px; background:var(--line); border-radius:3px; overflow:hidden; margin-top:8px; }
  .bar > i { display:block; height:100%; background:var(--accent); width:0; transition:width .2s; }
  .warning { margin-top:8px; padding:8px 10px; border-radius:8px; font-size:13px;
             background:#fdf3d0; border:1px solid var(--warn); color:#5c4404; }
  main { max-width:1180px; margin:0 auto; padding:16px; }
  .card { background:var(--card); border:1px solid var(--line); border-radius:10px; padding:16px; }
  .case { font-size:22px; font-weight:600; margin:0 0 4px; }
  .meta { display:flex; gap:14px; flex-wrap:wrap; margin-bottom:12px; }
  .comment { max-height:150px; overflow:auto; background:var(--bg); border:1px solid var(--line);
             border-radius:8px; padding:10px; white-space:pre-wrap; font-size:14px; margin-bottom:16px; }
  .cand { border:1px solid var(--line); border-radius:10px; padding:14px; margin-bottom:14px; }
  .cand.judged { border-color:var(--accent); }
  .cand-head { display:flex; gap:12px; align-items:baseline; flex-wrap:wrap; margin-bottom:10px; }
  .cand-head .what { font-size:17px; font-weight:600; }
  .badge { font-size:12px; padding:2px 8px; border-radius:99px; border:1px solid var(--line); }
  .badge.taken { border-color:var(--ok); color:var(--ok); }
  .badge.dropped { border-color:var(--warn); color:var(--warn); }
  .split { display:grid; grid-template-columns:1fr 1fr; gap:14px; align-items:start; }
  @media (max-width:900px) { .split { grid-template-columns:1fr; } }
  iframe { width:100%; height:300px; border:1px solid var(--line); border-radius:8px; background:var(--bg); }
  .queries { font-size:13px; color:var(--muted); }
  .queries div { margin-bottom:4px; word-break:break-word; }
  button { font:inherit; padding:9px 15px; border-radius:8px; border:1px solid var(--line);
           background:var(--card); color:var(--text); cursor:pointer; }
  button:hover { border-color:var(--accent); }
  .buttons { display:flex; gap:9px; flex-wrap:wrap; margin-top:12px; }
  button.pick { font-weight:600; }
  button.pick.ok { border-color:var(--ok); color:var(--ok); }
  button.pick.bad { border-color:var(--bad); color:var(--bad); }
  button.pick.warn { border-color:var(--warn); color:var(--warn); }
  button.pick.chosen { background:var(--accent); border-color:var(--accent); color:#fff; }
  .note { width:100%; margin-top:12px; padding:8px 10px; border-radius:8px;
          border:1px solid var(--line); background:var(--bg); color:var(--text); font:inherit; }
  .nav { display:flex; gap:10px; align-items:center; margin-top:8px; }
  .nav input { flex:1; }
  kbd { border:1px solid var(--line); border-bottom-width:2px; border-radius:4px;
        padding:1px 5px; font-size:12px; font-family:ui-monospace, monospace; }
  a { color:var(--accent); }
</style>
</head>
<body>
<header>
  <div class="head">
    <b>Разметка геокодинга</b>
    <span class="muted" id="counter"></span>
    <span class="muted" id="tally"></span>
    <span style="margin-left:auto"></span>
    <button id="export">Скачать результат</button>
  </div>
  <div id="warning" class="warning" hidden></div>
  <div class="bar"><i id="progress"></i></div>
</header>
<main id="root"></main>

<script>
const ROWS = __ROWS__;
const VERDICTS = __VERDICTS__;
const STORAGE_KEY = "geo-review-" + __KEY__;
const SERVED = location.protocol === "http:" || location.protocol === "https:";

const HINTS = {
  "верно": "Место то самое, о котором говорит житель.",
  "неверно": "Другой город, район или улица.",
  "не адрес": "В кейсе нет адреса — точки быть не должно.",
};
const STYLE = { "верно": "ok", "неверно": "bad", "не адрес": "warn" };

const TOTAL = ROWS.reduce((sum, row) => sum + row.candidates.length, 0);

let storageWorks = true;
try {
  localStorage.setItem(STORAGE_KEY + "-probe", "1");
  localStorage.removeItem(STORAGE_KEY + "-probe");
} catch (e) { storageWorks = false; }

let answers = {};
try { answers = JSON.parse(localStorage.getItem(STORAGE_KEY) || "{}"); } catch (e) { answers = {}; }

if (!storageWorks && !SERVED) {
  const banner = document.getElementById("warning");
  banner.hidden = false;
  banner.textContent = "Браузер запретил сохранение прогресса для файла с диска. " +
    "Разметка не переживёт перезагрузку — скачивайте результат почаще, либо запустите " +
    "страницу через: python -m tools.geo_review <файлы.xlsx> --serve";
}

function done(row) {
  return row.candidates.every(c => (answers[c.key] || {}).verdict);
}

let index = ROWS.findIndex(row => !done(row));
if (index < 0) index = ROWS.length ? ROWS.length - 1 : 0;

function save() {
  try { localStorage.setItem(STORAGE_KEY, JSON.stringify(answers)); } catch (e) {}
  if (SERVED) {
    fetch("/verdicts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(answers),
    }).catch(() => {});
  }
}

function setVerdict(candidate, verdict) {
  const current = answers[candidate.key] || {};
  answers[candidate.key] = {
    verdict: current.verdict === verdict ? "" : verdict,
    note: current.note || "",
    coordinate: candidate.coordinate,
  };
  save();
  if (done(ROWS[index])) {
    const next = ROWS.findIndex((row, i) => i > index && !done(row));
    if (next >= 0) index = next;
  }
  render();
}

function esc(value) {
  return String(value == null ? "" : value).replace(/[&<>"]/g, c =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
}

function render() {
  const answered = Object.values(answers).filter(a => a && a.verdict).length;
  document.getElementById("counter").textContent =
    ROWS.length ? "кейс " + (index + 1) + " из " + ROWS.length : "нет строк";
  document.getElementById("progress").style.width = (TOTAL ? answered / TOTAL * 100 : 0) + "%";

  const tally = {};
  Object.values(answers).forEach(a => {
    if (a && a.verdict) tally[a.verdict] = (tally[a.verdict] || 0) + 1;
  });
  document.getElementById("tally").textContent =
    "мест размечено " + answered + " из " + TOTAL +
    (Object.keys(tally).length ? " · " + Object.entries(tally).map(([k, n]) => k + ": " + n).join(" · ") : "");

  const root = document.getElementById("root");
  if (!ROWS.length) { root.innerHTML = "<div class='card'>Размечать нечего.</div>"; return; }

  const row = ROWS[index];
  const cards = row.candidates.map((candidate, position) => {
    const picked = (answers[candidate.key] || {}).verdict || "";
    const badges = candidate.providers.map(p =>
      '<span class="badge ' + (p.taken ? "taken" : "dropped") + '">' + esc(p.name) +
      (p.taken ? "" : " · отвергнут фильтром") + '</span>').join(" ");
    const buttons = VERDICTS.map((v, i) =>
      '<button class="pick ' + STYLE[v] + (picked === v ? " chosen" : "") +
      '" data-key="' + esc(candidate.key) + '" data-verdict="' + esc(v) + '" title="' +
      esc(HINTS[v]) + '"><kbd>' + (position * VERDICTS.length + i + 1) + '</kbd> ' + esc(v) + '</button>').join("");
    return '<div class="cand' + (picked ? " judged" : "") + '">' +
        '<div class="cand-head"><span class="what">' + esc(candidate.text) + '</span>' + badges + '</div>' +
        '<div class="split">' +
          '<div>' +
            '<div class="queries">' + candidate.queries.map(q => "<div>по запросу: " + esc(q) + "</div>").join("") + '</div>' +
            '<div class="buttons">' + buttons + '</div>' +
          '</div>' +
          '<div><iframe loading="lazy" src="https://yandex.ru/map-widget/v1/?ll=' +
            encodeURIComponent(candidate.lon + "," + candidate.lat) + '&z=16&pt=' +
            encodeURIComponent(candidate.lon + "," + candidate.lat) + '"></iframe>' +
            '<div class="muted"><a href="https://yandex.ru/maps/?pt=' +
            encodeURIComponent(candidate.lon + "," + candidate.lat) +
            '&z=17&l=map" target="_blank" rel="noopener">открыть карту отдельно</a></div></div>' +
        '</div>' +
      '</div>';
  }).join("");

  root.innerHTML =
    '<div class="card">' +
      '<p class="case">' + esc(row.case) + '</p>' +
      '<div class="meta muted"><span>' + esc(row.public) + '</span>' +
        '<span>слой: ' + esc(row.layer) + '</span>' +
        (row.city ? '<span>город паблика: ' + esc(row.city) + '</span>' : '') +
        '<span>вариантов места: ' + row.candidates.length + '</span></div>' +
      '<div class="comment">' + (esc(row.comment) || "—") + '</div>' +
      cards +
      '<input class="note" id="note" placeholder="заметка по кейсу" value="' +
        esc((answers[row.candidates[0].key] || {}).note || "") + '">' +
      '<div class="nav">' +
        '<button id="prev"><kbd>&larr;</kbd> назад</button>' +
        '<button id="next">вперёд <kbd>&rarr;</kbd></button>' +
        '<input type="range" id="jump" min="1" max="' + ROWS.length + '" value="' + (index + 1) + '">' +
      '</div>' +
    '</div>';

  root.querySelectorAll("[data-verdict]").forEach(button => {
    button.onclick = () => {
      const candidate = row.candidates.find(c => c.key === button.dataset.key);
      setVerdict(candidate, button.dataset.verdict);
    };
  });
  document.getElementById("prev").onclick = () => { index = Math.max(0, index - 1); render(); };
  document.getElementById("next").onclick = () => { index = Math.min(ROWS.length - 1, index + 1); render(); };
  document.getElementById("jump").oninput = event => { index = +event.target.value - 1; render(); };
  document.getElementById("note").oninput = event => {
    const candidate = row.candidates[0];
    const current = answers[candidate.key] || { verdict: "" };
    answers[candidate.key] = {
      verdict: current.verdict || "",
      note: event.target.value,
      coordinate: candidate.coordinate,
    };
    save();
  };
}

document.addEventListener("keydown", event => {
  if (event.target.tagName === "INPUT") return;
  const row = ROWS[index];
  if (!row) return;
  if (event.key === "ArrowLeft") { index = Math.max(0, index - 1); render(); return; }
  if (event.key === "ArrowRight") { index = Math.min(ROWS.length - 1, index + 1); render(); return; }
  const slot = parseInt(event.key, 10);
  if (!(slot >= 1)) return;
  const candidate = row.candidates[Math.floor((slot - 1) / VERDICTS.length)];
  const verdict = VERDICTS[(slot - 1) % VERDICTS.length];
  if (candidate && verdict) setVerdict(candidate, verdict);
});

document.getElementById("export").onclick = () => {
  const eol = String.fromCharCode(13, 10);
  const cell = value => '"' + String(value == null ? "" : value).replace(/"/g, '""') + '"';
  const lines = [["id", "координата", "вердикт", "заметка"].map(cell).join(",")];
  Object.entries(answers).forEach(([key, answer]) => {
    if (answer && (answer.verdict || answer.note)) {
      lines.push([key.split("#")[0], answer.coordinate || "", answer.verdict || "", answer.note || ""]
        .map(cell).join(","));
    }
  });
  const blob = new Blob([String.fromCharCode(65279) + lines.join(eol)], { type: "text/csv;charset=utf-8" });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = "verdicts.csv";
  link.click();
  URL.revokeObjectURL(link.href);
};

render();
</script>
</body>
</html>
"""


def _parse_point(row: dict) -> tuple[float, float] | None:
    raw = str(row.get("координата") or "")
    if not raw:
        return None
    lat, _, lon = raw.partition(",")
    try:
        return float(lat), float(lon)
    except ValueError:
        return None


def _collect(tables: list[tuple[str, dict]], case_id: str) -> list[dict]:
    """Схлопывает ответы провайдеров, указывающие на одно и то же место."""
    places: list[dict] = []
    for name, table in tables:
        row = table.get(case_id)
        if row is None:
            continue
        point = _parse_point(row)
        if point is None:
            continue
        provider = {"name": name, "taken": str(row.get("статус") or "") == STATUS_FOUND}
        query = str(row.get("запрос") or "")
        for place in places:
            if distance_km((place["lat"], place["lon"]), point) <= SAME_PLACE_KM:
                place["providers"].append(provider)
                if query and query not in place["queries"]:
                    place["queries"].append(query)
                break
        else:
            places.append({
                "lat": point[0],
                "lon": point[1],
                "text": str(row.get("что нашёл геокодер") or ""),
                "coordinate": f"{point[0]}, {point[1]}",
                "providers": [provider],
                "queries": [query] if query else [],
            })
    return places


def _provider_name(path: str) -> str:
    """«geo_label-2gis-2026-08-26.xlsx» → «2gis»."""
    stem = Path(path).stem
    for prefix in ("geo_label-", "geo_label_"):
        if stem.startswith(prefix):
            stem = stem[len(prefix):]
    return re.sub(r"[-_]\d{4}-\d{2}-\d{2}$", "", stem)


def build_page(paths: list[str], out: str) -> None:
    tables = [
        (_provider_name(path), {str(row.get("id") or ""): row for row in _read(path)})
        for path in paths
    ]

    rows = []
    for case_id, base_row in tables[0][1].items():
        candidates = _collect(tables, case_id)
        if not candidates:
            continue
        for position, candidate in enumerate(candidates):
            candidate["key"] = f"{case_id}#{position}"
        rows.append({
            "id": case_id,
            "layer": str(base_row.get("слой") or ""),
            "public": str(base_row.get("паблик") or ""),
            "city": str(base_row.get("город паблика") or ""),
            "case": str(base_row.get("адресный кейс") or ""),
            "comment": str(base_row.get("комментарий") or ""),
            "candidates": candidates,
        })

    page = (
        TEMPLATE
        .replace("__ROWS__", json.dumps(rows, ensure_ascii=False))
        .replace("__VERDICTS__", json.dumps(list(VERDICTS), ensure_ascii=False))
        .replace("__KEY__", json.dumps("+".join(name for name, _ in tables)))
    )
    Path(out).write_text(page, encoding="utf-8")

    total = sum(len(row["candidates"]) for row in rows)
    print(f"провайдеров: {len(tables)} ({', '.join(name for name, _ in tables)})")
    print(f"кейсов: {len(rows)}, мест к разметке: {total}")
    if rows:
        print(f"мест на кейс в среднем: {total / len(rows):.2f}")
    print(f"страница: {out}")


def serve(page: str, verdicts_path: str, port: int) -> None:
    """Отдаёт страницу с localhost и пишет вердикты на диск после каждого клика."""
    body = Path(page).read_bytes()
    target = Path(verdicts_path)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            length = int(self.headers.get("Content-Length") or 0)
            answers = json.loads(self.rfile.read(length) or b"{}")
            with target.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(["id", "координата", "вердикт", "заметка"])
                for key, answer in sorted(answers.items()):
                    verdict = (answer or {}).get("verdict") or ""
                    note = (answer or {}).get("note") or ""
                    if verdict or note:
                        writer.writerow([
                            key.split("#")[0],
                            (answer or {}).get("coordinate") or "",
                            verdict,
                            note,
                        ])
            self.send_response(204)
            self.end_headers()

        def log_message(self, *_args):
            pass

    print(f"страница: http://localhost:{port}")
    print(f"вердикты пишутся в {target} после каждого клика")
    print("остановить — Ctrl+C")
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", help="файлы geo_label; первый задаёт список кейсов")
    parser.add_argument("--out", default="geo_review.html", help="куда сохранить страницу")
    parser.add_argument("--serve", action="store_true", help="открыть страницу на localhost")
    parser.add_argument("--verdicts", default="verdicts.csv", help="куда писать вердикты при --serve")
    parser.add_argument("--port", type=int, default=8770)
    args = parser.parse_args()
    build_page(args.paths, args.out)
    if args.serve:
        serve(args.out, args.verdicts, args.port)


if __name__ == "__main__":
    main()
