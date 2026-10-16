"""Оценка rule-based классификации болей на эталонном наборе.

Прогоняет текущий rule-путь (без LLM) на текстах из data/eval/eval_set.jsonl и
сравнивает с разметкой куратора (gold_is_pain ∈ {0,1}, gold_category). Запускать
до и после изменений правил, чтобы видеть, как меняются точность и полнота.

Запуск:  python -m tools.eval_rules
"""
from __future__ import annotations

import json
from pathlib import Path

from backend.db.enums import RelevanceEnum, SentimentEnum
from backend.modules.analytics.utils.category_classifier import normalize_hierarchy_values
from backend.modules.analytics.utils.official_response import (
    is_community_authored,
    looks_like_official_response,
)
from backend.modules.analytics.utils.sentiment_rules import (
    fallback_relevance,
    has_request_signal,
    looks_like_noise_non_pain,
    looks_sarcastic,
    sentiment_for_text,
    topics_for_text,
)

EVAL_PATH = Path("data/eval/eval_set.jsonl")


def classify_rule(text: str, author_external_id=None) -> tuple[bool, str]:
    """Повторяет решение rule-пути билдера: боль ли это и какая категория."""
    if is_community_authored(author_external_id) or looks_like_official_response(text, None):
        return False, ""
    if looks_like_noise_non_pain(text):
        return False, ""
    topics = topics_for_text(text)
    sentiment = sentiment_for_text(text)
    has_req = has_request_signal(text)
    if looks_sarcastic(text):
        sentiment = SentimentEnum.negative
    if fallback_relevance(topics, has_req, sentiment) != RelevanceEnum.relevant:
        return False, ""
    if not has_req and sentiment not in (SentimentEnum.negative, SentimentEnum.positive):
        return False, ""
    category, _, _ = normalize_hierarchy_values(
        category="", subcategory="", case_name="", source_text=text
    )
    return True, category


def main() -> None:
    rows = [json.loads(line) for line in EVAL_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]
    labeled = [r for r in rows if str(r.get("gold_is_pain", "")).strip() in {"0", "1"}]

    if not labeled:
        agree = sum(
            1 for r in rows
            if classify_rule(r["text"])[0] == (r["stratum"] == "pain")
        )
        print(f"Размечено 0 из {len(rows)} строк — gold_is_pain ещё не заполнен.")
        print("Заполни data/eval/eval_set.csv (gold_is_pain 0/1, gold_category) и перезапусти.")
        print(f"Пока для справки: rule-путь совпадает с текущим sys-решением в {agree}/{len(rows)}.")
        return

    tp = fp = fn = tn = 0
    cat_hit = cat_total = 0
    for r in labeled:
        gold = r["gold_is_pain"].strip() == "1"
        pred, pred_cat = classify_rule(r["text"])
        if pred and gold:
            tp += 1
            gold_cat = (r.get("gold_category") or "").strip()
            if gold_cat:
                cat_total += 1
                cat_hit += int(pred_cat == gold_cat)
        elif pred and not gold:
            fp += 1
        elif not pred and gold:
            fn += 1
        else:
            tn += 1

    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    false_pain = fp / (tp + fp) if (tp + fp) else 0.0
    print(f"Размечено: {len(labeled)} строк")
    print(f"TP={tp} FP={fp} FN={fn} TN={tn}")
    print(f"Точность (precision): {precision:.1%}  | боль-точность")
    print(f"Полнота  (recall):    {recall:.1%}")
    print(f"Доля ложных болей:    {false_pain:.1%}")
    if cat_total:
        print(f"Категория верна на TP: {cat_hit}/{cat_total} ({cat_hit / cat_total:.1%})")


if __name__ == "__main__":
    main()
