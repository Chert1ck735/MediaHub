"""Замер префильтра на qwen2.5-3b: режет ли шум, не теряя боли.

Гоняет gold-комменты через лёгкий бинарный гейт на 3b и считает:
  - recall болей (сколько настоящих болей сохранил — терять нельзя),
  - сколько шума отсёк (выигрыш по нагрузке на большую 14b),
  - пропускную способность 3b,
  - ОШИБКИ ЛЛМ (если сервер молчал — иначе recall ложно «100%»).
Не трогает 14b и llm_pred.jsonl.

Запуск локально (ollama):   python -m tools.prefilter_probe_3b
Запуск с сервера:           PRE3B_PROVIDER=openai python -m tools.prefilter_probe_3b
Env:  PRE3B_PROVIDER=ollama|openai   PRE3B_CONCURRENCY=8   PRE3B_MODEL=...
"""
from __future__ import annotations

import glob
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from backend.app.config import settings

EVAL = Path("data/eval")
PROVIDER = os.getenv("PRE3B_PROVIDER", "ollama")
CONC = int(os.getenv("PRE3B_CONCURRENCY", "8"))

# Детектор ШУМА, а не болей: лёгкое направление для 3b. Дропаем при «мусор»,
# пропускаем при «обращение». Few-shot — малые модели на примерах точнее.
SYSTEM = (
    "Ты сортируешь комментарии в паблике на два класса.\n"
    "МУСОР — чистая благодарность/похвала без проблемы, поздравление, реклама/спам, "
    "флуд и смайлы, оффтоп не про город.\n"
    "ОБРАЩЕНИЕ — есть любая проблема, нехватка, претензия, просьба, упомянут объект/услуга/место; "
    "даже если коротко, косвенно или с иронией.\n"
    "Примеры МУСОР: «Спасибо, молодцы!»; «С праздником вас!»; «👍👍👍»; «Куплю авто дорого, пишите».\n"
    "Примеры ОБРАЩЕНИЕ: «Спасибо за ответ, но школы так и нет»; «ТЭЦ газифицировать бы»; "
    "«Опять яму объезжаю»; «Мусор две недели не вывозят».\n"
    "Ответь ОДНИМ словом: МУСОР или ОБРАЩЕНИЕ."
)


def _make_client():
    if PROVIDER == "openai":
        from backend.modules.llm.providers.openai_compatible_client import OpenAICompatibleClient
        model = os.getenv("PRE3B_MODEL", "huggingface.co/qwen/qwen2.5-3b-instruct-gguf:latest")
        client = OpenAICompatibleClient(
            model=model, base_url=settings.OPENAI_COMPATIBLE_BASE_URL,
            num_predict=5, temperature=0.0, usage_context="prefilter_probe",
        )
        return client, model, settings.OPENAI_COMPATIBLE_BASE_URL
    from backend.modules.llm.providers.ollama_client import QwenClient
    model = os.getenv("PRE3B_MODEL", "qwen2.5:3b")
    client = QwenClient(model=model, num_predict=5, temperature=0.0, usage_context="prefilter_probe")
    return client, model, client.base_url


def _load():
    base = {}
    for fn, sub in (("eval_set.jsonl", "representative"), ("augment.jsonl", "augment")):
        p = EVAL / fn
        if p.exists():
            for l in p.read_text(encoding="utf-8").splitlines():
                if l.strip():
                    r = json.loads(l); r.setdefault("subset", sub); base[r["comment_id"]] = r
    for gf in glob.glob(str(EVAL / "parts" / "gold_*.jsonl")):
        for l in Path(gf).read_text(encoding="utf-8").splitlines():
            if l.strip():
                g = json.loads(l); cid = g.get("comment_id")
                if cid in base:
                    base[cid].update({k: v for k, v in g.items() if k.startswith("gold_")})
    corr = EVAL / "corrections.jsonl"
    if corr.exists():
        for l in corr.read_text(encoding="utf-8").splitlines():
            if l.strip():
                c = json.loads(l); r = base.get(c.get("comment_id"))
                if r: r.update({k: v for k, v in c.items() if k.startswith("gold_")})
    return [r for r in base.values() if str(r.get("gold_is_pain", "")) in ("0", "1")]


def _classify(client, text):
    """Возвращает ('keep'|'drop', error|None). keep = пропустить дальше в 14b."""
    try:
        ans = client.generate([
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": text[:1500]},
        ]).strip().lower()
    except Exception as exc:
        return "keep", str(exc)[:120]  # на ошибке не теряем — но считаем как ошибку
    return ("drop" if ans.startswith("мус") else "keep"), None  # «мус» — на случай обрезки токенов


def main() -> None:
    client, model, where = _make_client()
    print(f"Префильтр provider={PROVIDER}  модель={model}\n  адрес={where}  параллельность={CONC}", flush=True)

    # preflight: видим живой сырой ответ до прогона
    for probe in ("Спасибо, молодцы!", "Опять яму на дороге объезжаю"):
        try:
            raw = client.generate([{"role": "system", "content": SYSTEM},
                                   {"role": "user", "content": probe}]).strip()
            print(f"  preflight «{probe[:30]}» → {raw!r}", flush=True)
        except Exception as exc:
            print(f"  preflight ОШИБКА: {str(exc)[:160]}\n  ЛЛМ недоступна — прогон отменён.")
            return

    rows = _load()
    total = len(rows)
    print(f"  комментов={total}\n", flush=True)

    verdicts: list[str] = ["keep"] * total
    errors = 0
    t0 = time.perf_counter(); last = [t0]; done = 0
    with ThreadPoolExecutor(max_workers=CONC) as ex:
        futs = {ex.submit(_classify, client, r.get("text", "")): i for i, r in enumerate(rows)}
        for fut in as_completed(futs):
            i = futs[fut]
            verdicts[i], err = fut.result()
            if err:
                errors += 1
            done += 1
            now = time.perf_counter()
            if done == total or now - last[0] >= 15:
                last[0] = now
                print(f"  {done}/{total}  ошибок:{errors}  ~{done/(now-t0)*60:.0f}/мин", flush=True)
    elapsed = time.perf_counter() - t0

    keeps = [v == "keep" for v in verdicts]
    pains = [(r, k) for r, k in zip(rows, keeps) if str(r["gold_is_pain"]) == "1"]
    noise = [(r, k) for r, k in zip(rows, keeps) if str(r["gold_is_pain"]) == "0"]
    pain_kept = sum(1 for _, k in pains if k)
    noise_dropped = sum(1 for _, k in noise if not k)
    sent_on = sum(1 for k in keeps if k)

    print(f"\n=== ПРЕФИЛЬТР 3b на gold ({total} комментов, {elapsed:.0f}с, {total/elapsed*60:.0f}/мин)")
    if errors:
        print(f"!!! ОШИБОК ЛЛМ: {errors}/{total} ({errors/total:.0%}) — на них боль НЕ терялась, "
              f"но цифры ниже занижают отсев. {'РЕЗУЛЬТАТ НЕДЕЙСТВИТЕЛЕН.' if errors/total > 0.1 else ''}")
    print(f"recall болей: {pain_kept}/{len(pains)} ({pain_kept/len(pains):.0%})  "
          f"— ПОТЕРЯНО болей: {len(pains)-pain_kept}")
    print(f"шум отсечён:  {noise_dropped}/{len(noise)} ({noise_dropped/len(noise):.0%})")
    print(f"ушло бы в 14b: {sent_on}/{total} ({sent_on/total:.0%})  "
          f"→ экономия нагрузки на 14b ~{(1-sent_on/total):.0%}")

    lost = [r for (r, k) in pains if not k]
    if lost:
        print(f"\nПОТЕРЯННЫЕ БОЛИ (3b ошибочно отсёк — это плохо), до 15:")
        for r in lost[:15]:
            print(f"  [{r.get('gold_category','')}] {r.get('text','')[:90]}")


if __name__ == "__main__":
    main()
