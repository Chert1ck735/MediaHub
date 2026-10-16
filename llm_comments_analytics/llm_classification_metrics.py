# scripts/fill_dataset_with_llm.py

import asyncio

import pandas as pd
from sklearn.metrics import (
    accuracy_score,
    classification_report,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
)

from backend.modules.llm.service import analyze_comment


INPUT = "data/classification_dataset_fixed.csv"
OUTPUT = "data/classification_dataset_llm_filled_2.csv"


def empty(value) -> bool:
    return pd.isna(value) or str(value).strip() == ""


def normalize(value) -> str:
    if pd.isna(value):
        return ""
    return str(value).strip()


async def classify_row(comment: str):
    return await analyze_comment(comment)


def calculate_and_print_metrics(df: pd.DataFrame) -> None:
    metric_pairs = [
        ("relevance", "true_relevance", "predicted_relevance"),
        ("sentiment", "true_sentiment", "predicted_sentiment"),
        ("message_type", "true_message_type", "predicted_message_type"),
        ("category", "true_category", "predicted_category"),
        ("subcategory", "true_subcategory", "predicted_subcategory"),
        ("case", "true_case", "predicted_case"),
    ]

    print("\n" + "=" * 80)
    print("METRICS")
    print("=" * 80)

    for title, true_col, pred_col in metric_pairs:
        if true_col not in df.columns or pred_col not in df.columns:
            print(f"\n[{title}] skipped: columns not found")
            continue

        part = df[[true_col, pred_col]].copy()
        part[true_col] = part[true_col].map(normalize)
        part[pred_col] = part[pred_col].map(normalize)

        part = part[
            (part[true_col] != "") &
            (part[pred_col] != "")
        ]

        print("\n" + "-" * 80)
        print(title.upper())
        print("-" * 80)

        if part.empty:
            print("Нет данных для расчёта метрик.")
            continue

        y_true = part[true_col]
        y_pred = part[pred_col]
        labels = sorted(set(y_true) | set(y_pred))

        print(f"Rows: {len(part)}")
        print(f"Accuracy:        {accuracy_score(y_true, y_pred):.4f}")
        print(f"Precision macro: {precision_score(y_true, y_pred, average='macro', zero_division=0):.4f}")
        print(f"Recall macro:    {recall_score(y_true, y_pred, average='macro', zero_division=0):.4f}")
        print(f"F1 macro:        {f1_score(y_true, y_pred, average='macro', zero_division=0):.4f}")

        print("\nClassification report:")
        print(
            classification_report(
                y_true,
                y_pred,
                labels=labels,
                zero_division=0,
            )
        )

        print("Confusion matrix:")
        print(f"Labels: {labels}")
        print(confusion_matrix(y_true, y_pred, labels=labels))


def print_relevance_errors(df: pd.DataFrame) -> None:
    true_col = "true_relevance"
    pred_col = "predicted_relevance"

    part = df[[true_col, pred_col, "comment"]].copy()
    part[true_col] = part[true_col].map(normalize)
    part[pred_col] = part[pred_col].map(normalize)

    errors = part[
        (part[true_col] != "") &
        (part[pred_col] != "") &
        (part[true_col] != part[pred_col])
    ]

    print("\n" + "=" * 80)
    print(f"RELEVANCE ERRORS: {len(errors)}")
    print("=" * 80)

    for idx, row in errors.iterrows():
        print("-" * 80)
        print(f"index: {idx}")
        print(f"true:  {row[true_col]}")
        print(f"pred:  {row[pred_col]}")
        print(f"text:  {row['comment']}")


async def main() -> None:
    df = pd.read_csv(INPUT)

    for idx, row in df.iterrows():
        comment = str(row["comment"] or "").strip()

        if not comment:
            continue

        if not empty(row.get("predicted_relevance")):
            continue

        try:
            result = await classify_row(comment)

            df.loc[idx, "predicted_relevance"] = normalize(result.relevance)
            df.loc[idx, "predicted_sentiment"] = normalize(result.sentiment)
            df.loc[idx, "predicted_message_type"] = normalize(result.message_type)

            hierarchy = result.hierarchy
            df.loc[idx, "predicted_category"] = normalize(
                hierarchy.category if hierarchy else ""
            )
            df.loc[idx, "predicted_subcategory"] = normalize(
                hierarchy.subcategory if hierarchy else ""
            )
            df.loc[idx, "predicted_case"] = normalize(
                hierarchy.case if hierarchy else ""
            )

            print(f"[OK] {idx}: {result.relevance}")

        except Exception as exc:
            print(f"[ERROR] {idx}: {exc}")

        df.to_csv(OUTPUT, index=False, encoding="utf-8-sig")

    df.to_csv(OUTPUT, index=False, encoding="utf-8-sig")

    calculate_and_print_metrics(df)
    print_relevance_errors(df)

    print("\n" + "=" * 80)
    print(f"Saved dataset to: {OUTPUT}")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(main())