import asyncio
import json
from datetime import datetime
from pathlib import Path

import mlflow
import pandas as pd
from sklearn.metrics import f1_score, recall_score, precision_score, accuracy_score

from backend.modules.llm.service import analyze_comment


INPUT = "data/classification_dataset_fixed.csv"
EXPERIMENT_NAME = "llm-comment-classification"
PROMPTS_DIR = Path("prompts/comment_analysis")

OUTPUT_ROOT = Path("data/mlflow_runs")

PREDICTED_COLUMNS = [
    "predicted_relevance",
    "predicted_sentiment",
    "predicted_message_type",
    "predicted_category",
    "predicted_subcategory",
    "predicted_case",
]

METRIC_PAIRS = [
    ("relevance", "true_relevance", "predicted_relevance"),
    ("sentiment", "true_sentiment", "predicted_sentiment"),
    ("message_type", "true_message_type", "predicted_message_type"),
    ("category", "true_category", "predicted_category"),
    ("subcategory", "true_subcategory", "predicted_subcategory"),
    ("case", "true_case", "predicted_case"),
]

EXPERIMENTS = [
# ---------- SYSTEM V1 ----------

    {
        "run_name": "system_v1_t01",
        "system_prompt_template": "analysis/system.md",
        "temperature": 0.1,
        "top_p": 1.0,
        "top_k": None,
        "repeat_penalty": 1.02,
    },
    {
        "run_name": "system_v1_t02",
        "system_prompt_template": "analysis/system.md",
        "temperature": 0.2,
        "top_p": 1.0,
        "top_k": None,
        "repeat_penalty": 1.02,
    },
    {
        "run_name": "system_v1_t03",
        "system_prompt_template": "analysis/system.md",
        "temperature": 0.3,
        "top_p": 1.0,
        "top_k": None,
        "repeat_penalty": 1.02,
    },
    {
        "run_name": "system_v1_t04",
        "system_prompt_template": "analysis/system.md",
        "temperature": 0.4,
        "top_p": 1.0,
        "top_k": None,
        "repeat_penalty": 1.02,
    },
    {
        "run_name": "system_v1_t05",
        "system_prompt_template": "analysis/system.md",
        "temperature": 0.5,
        "top_p": 1.0,
        "top_k": None,
        "repeat_penalty": 1.02,
    },
    {
        "run_name": "system_v1_t06",
        "system_prompt_template": "analysis/system.md",
        "temperature": 0.6,
        "top_p": 1.0,
        "top_k": None,
        "repeat_penalty": 1.02,
    },

    {
        "run_name": "system_v1_top_k",
        "system_prompt_template": "analysis/system.md",
        "temperature": 0.1,
        "top_p": 1.0,
        "top_k": 20,
        "repeat_penalty": 1.02,
    },

    {
        "run_name": "system_v1_top_p",
        "system_prompt_template": "analysis/system.md",
        "temperature": 0.1,
        "top_p": 0.9,
        "top_k": None,
        "repeat_penalty": 1.02,
    },

    {
        "run_name": "system_v1_top_k_top_p",
        "system_prompt_template": "analysis/system.md",
        "temperature": 0.1,
        "top_p": 0.9,
        "top_k": 20,
        "repeat_penalty": 1.02,
    },

    # ---------- SYSTEM V2 ----------

    {
        "run_name": "system_v2_t01",
        "system_prompt_template": "analysis/system2.md",
        "temperature": 0.1,
        "top_p": 1.0,
        "top_k": None,
        "repeat_penalty": 1.02,
    },
    {
        "run_name": "system_v2_t02",
        "system_prompt_template": "analysis/system2.md",
        "temperature": 0.2,
        "top_p": 1.0,
        "top_k": None,
        "repeat_penalty": 1.02,
    },
    {
        "run_name": "system_v2_t03",
        "system_prompt_template": "analysis/system2.md",
        "temperature": 0.3,
        "top_p": 1.0,
        "top_k": None,
        "repeat_penalty": 1.02,
    },
    {
        "run_name": "system_v2_t04",
        "system_prompt_template": "analysis/system2.md",
        "temperature": 0.4,
        "top_p": 1.0,
        "top_k": None,
        "repeat_penalty": 1.02,
    },
    {
        "run_name": "system_v2_t05",
        "system_prompt_template": "analysis/system2.md",
        "temperature": 0.5,
        "top_p": 1.0,
        "top_k": None,
        "repeat_penalty": 1.02,
    },
    {
        "run_name": "system_v2_t06",
        "system_prompt_template": "analysis/system2.md",
        "temperature": 0.6,
        "top_p": 1.0,
        "top_k": None,
        "repeat_penalty": 1.02,
    },

    {
        "run_name": "system_v2_top_k",
        "system_prompt_template": "analysis/system2.md",
        "temperature": 0.1,
        "top_p": 1.0,
        "top_k": 20,
        "repeat_penalty": 1.02,
    },

    {
        "run_name": "system_v2_top_p",
        "system_prompt_template": "analysis/system2.md",
        "temperature": 0.1,
        "top_p": 0.9,
        "top_k": None,
        "repeat_penalty": 1.02,
    },

    {
        "run_name": "system_v2_top_k_top_p",
        "system_prompt_template": "analysis/system2.md",
        "temperature": 0.1,
        "top_p": 0.9,
        "top_k": 20,
        "repeat_penalty": 1.02,
    },

]

EXPERIMENTS = [
# ---------- SYSTEM V3 ----------

    {
        "run_name": "system_v3_t01",
        "system_prompt_template": "analysis/system3.md",
        "temperature": 0.1,
        "top_p": 1.0,
        "top_k": None,
        "repeat_penalty": 1.02,
    },
    {
        "run_name": "system_v3_t02",
        "system_prompt_template": "analysis/system3.md",
        "temperature": 0.2,
        "top_p": 1.0,
        "top_k": None,
        "repeat_penalty": 1.02,
    },
    {
        "run_name": "system_v3_t03",
        "system_prompt_template": "analysis/system3.md",
        "temperature": 0.3,
        "top_p": 1.0,
        "top_k": None,
        "repeat_penalty": 1.02,
    },
    {
        "run_name": "system_v3_t04",
        "system_prompt_template": "analysis/system3.md",
        "temperature": 0.4,
        "top_p": 1.0,
        "top_k": None,
        "repeat_penalty": 1.02,
    },
    {
        "run_name": "system_v3_t05",
        "system_prompt_template": "analysis/system3.md",
        "temperature": 0.5,
        "top_p": 1.0,
        "top_k": None,
        "repeat_penalty": 1.02,
    },
    {
        "run_name": "system_v3_t06",
        "system_prompt_template": "analysis/system3.md",
        "temperature": 0.6,
        "top_p": 1.0,
        "top_k": None,
        "repeat_penalty": 1.02,
    },

    {
        "run_name": "system_v3_top_k",
        "system_prompt_template": "analysis/system3.md",
        "temperature": 0.1,
        "top_p": 1.0,
        "top_k": 20,
        "repeat_penalty": 1.02,
    },

    {
        "run_name": "system_v3_top_p",
        "system_prompt_template": "analysis/system3.md",
        "temperature": 0.1,
        "top_p": 0.9,
        "top_k": None,
        "repeat_penalty": 1.02,
    },

    {
        "run_name": "system_v3_top_k_top_p",
        "system_prompt_template": "analysis/system3.md",
        "temperature": 0.1,
        "top_p": 0.9,
        "top_k": 20,
        "repeat_penalty": 1.02,
    },

]

def normalize(value) -> str:
    if pd.isna(value):
        return ""
    return str(value).strip()


def prepare_dataframe() -> pd.DataFrame:
    df = pd.read_csv(INPUT)

    for col in PREDICTED_COLUMNS:
        if col not in df.columns:
            df[col] = ""
        df[col] = df[col].astype("string")
        df[col] = ""

    return df

def load_text(path: str | None) -> str | None:
    if not path:
        return None
    return Path(path).read_text(encoding="utf-8")


async def classify_dataset(df: pd.DataFrame, config: dict) -> pd.DataFrame:
    for idx, row in df.iterrows():
        comment = normalize(row.get("comment"))

        if not comment:
            continue

        try:
            result = await analyze_comment(
                comment,
                temperature=config["temperature"],
                top_p=config["top_p"],
                top_k=config["top_k"],
                repeat_penalty=config["repeat_penalty"],
                system_prompt_template=config["system_prompt_template"]
            )

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

    return df


def calculate_metrics(df: pd.DataFrame) -> dict[str, float]:
    metrics: dict[str, float] = {}

    for title, true_col, pred_col in METRIC_PAIRS:
        part = df[[true_col, pred_col]].copy()
        part[true_col] = part[true_col].map(normalize)
        part[pred_col] = part[pred_col].map(normalize)

        part = part[
            (part[true_col] != "")
            & (part[pred_col] != "")
        ]

        if part.empty:
            continue

        y_true = part[true_col]
        y_pred = part[pred_col]

        metrics[f"{title}_accuracy"] = accuracy_score(y_true, y_pred)
        metrics[f"{title}_precision_macro"] = precision_score(
            y_true,
            y_pred,
            average="macro",
            zero_division=0,
        )
        metrics[f"{title}_recall_macro"] = recall_score(
            y_true,
            y_pred,
            average="macro",
            zero_division=0,
        )
        metrics[f"{title}_f1_macro"] = f1_score(
            y_true,
            y_pred,
            average="macro",
            zero_division=0,
        )

    return metrics


def save_errors(df: pd.DataFrame, output_dir: Path, field: str) -> Path:
    true_col = f"true_{field}"
    pred_col = f"predicted_{field}"

    part = df[[true_col, pred_col, "comment"]].copy()
    part[true_col] = part[true_col].map(normalize)
    part[pred_col] = part[pred_col].map(normalize)

    errors = part[
        (part[true_col] != "")
        & (part[pred_col] != "")
        & (part[true_col] != part[pred_col])
    ]

    path = output_dir / f"errors_{field}.csv"
    errors.to_csv(path, index=True, encoding="utf-8-sig")
    return path


def create_output_dir(config: dict, run_id: str) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    output_dir = (
        OUTPUT_ROOT
        / config["run_name"]
        / f"{timestamp}_{run_id[:8]}"
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


async def run_experiment(config: dict) -> None:

    with mlflow.start_run(run_name=config["run_name"]) as run:
        run_id = run.info.run_id

        output_dir = create_output_dir(config, run_id)

        mlflow.log_params(
            {
                "temperature": config["temperature"],
                "top_p": config["top_p"],
                "top_k": (
                    config["top_k"]
                    if config["top_k"] is not None
                    else "disabled"
                ),
                "repeat_penalty": config["repeat_penalty"],
                "dataset": INPUT,
                "output_dir": str(output_dir),
            }
        )

        df = prepare_dataframe()
        df = await classify_dataset(df, config)

        metrics = calculate_metrics(df)

        dataset_path = output_dir / "classification_dataset_llm_filled.csv"
        metrics_path = output_dir / "metrics.json"
        config_path = output_dir / "config.json"

        df.to_csv(dataset_path, index=False, encoding="utf-8-sig")

        metrics_path.write_text(
            json.dumps(metrics, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        config_path.write_text(
            json.dumps(config, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        errors_relevance_path = save_errors(df, output_dir, "relevance")
        errors_category_path = save_errors(df, output_dir, "category")
        errors_subcategory_path = save_errors(df, output_dir, "subcategory")

        for name, value in metrics.items():
            mlflow.log_metric(name, float(value))

        mlflow.log_artifact(str(dataset_path), artifact_path="datasets")
        mlflow.log_artifact(str(metrics_path), artifact_path="metrics")
        mlflow.log_artifact(str(config_path), artifact_path="configs")

        mlflow.log_artifact(str(errors_relevance_path), artifact_path="errors")
        mlflow.log_artifact(str(errors_category_path), artifact_path="errors")
        mlflow.log_artifact(str(errors_subcategory_path), artifact_path="errors")

        mlflow.set_tag("task", "llm_comment_classification")
        mlflow.set_tag("top_k_enabled", str(config["top_k"] is not None))
        mlflow.set_tag("top_p_enabled", str(config["top_p"] is not None))

        print("\n" + "=" * 80)
        print(f"RUN: {config['run_name']}")
        print(f"RUN ID: {run_id}")
        print(f"OUTPUT DATASET: {dataset_path}")
        print(json.dumps(metrics, ensure_ascii=False, indent=2))
        print("=" * 20)


async def main() -> None:
    mlflow.set_tracking_uri("sqlite:///mlflow.db")
    mlflow.set_experiment(EXPERIMENT_NAME)

    for config in EXPERIMENTS:
        await run_experiment(config)


if __name__ == "__main__":
    asyncio.run(main())