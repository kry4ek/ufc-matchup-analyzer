from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import GradientBoostingClassifier, RandomForestClassifier, VotingClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    balanced_accuracy_score,
    brier_score_loss,
    log_loss,
    roc_auc_score,
)
from sklearn.model_selection import StratifiedKFold, cross_val_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.models.model_registry import (
    ALL_CATEGORICAL_FEATURES,
    BASELINE_CATEGORICAL_FEATURES,
    DEFAULT_MODEL_VERSION,
    get_model_config,
    resolve_training_path,
    supported_model_versions,
    validate_model_features,
)


TARGET_COLUMN = "fighter_a_won"
CATEGORICAL_FEATURES = list(BASELINE_CATEGORICAL_FEATURES)
LEAKAGE_EXACT_COLUMNS = {
    "fight_id",
    "event_id",
    "event_date",
    "fighter_a_id",
    "fighter_b_id",
    "fighter_a",
    "fighter_b",
    "fighter_a_result",
    "fighter_b_result",
    TARGET_COLUMN,
    "method",
    "round",
    "time",
    "row_direction",
}
LEAKAGE_SUBSTRINGS = (
    "winner",
    "loser",
    "result",
    "method",
    "source_url",
    "referee",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Train first men's UFC baseline models with grouped chronological holdout."
    )
    parser.add_argument(
        "--model-version",
        default=DEFAULT_MODEL_VERSION,
        choices=supported_model_versions(),
        help="Registered men model version to train.",
    )
    parser.add_argument(
        "--training",
        default=None,
        help="Training CSV. Defaults to the selected model version's registered training file.",
    )
    parser.add_argument("--out-dir", default="models")
    parser.add_argument("--report", default="reports/sprint_3_baseline_model_report.md")
    parser.add_argument("--metrics-out", default="data/processed/baseline_metrics.json")
    parser.add_argument(
        "--predictions-out",
        default="data/processed/baseline_predictions_holdout.csv",
    )
    parser.add_argument("--holdout-start", default="2023-01-01")
    parser.add_argument("--skip-random-forest", action="store_true")
    parser.add_argument("--random-forest-estimators", type=int, default=250)
    return parser.parse_args()


def read_training(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(path)
    df = pd.read_csv(path)
    if TARGET_COLUMN not in df.columns:
        raise ValueError(f"Missing target column: {TARGET_COLUMN}")
    if "event_date" not in df.columns:
        raise ValueError("Missing event_date column")
    if "fight_id" not in df.columns:
        raise ValueError("Missing fight_id column")
    df["event_date"] = pd.to_datetime(df["event_date"], errors="coerce")
    df = df[pd.notna(df["event_date"])].copy()
    df = df[pd.notna(df[TARGET_COLUMN])].copy()
    df[TARGET_COLUMN] = df[TARGET_COLUMN].astype(int)
    for column in ALL_CATEGORICAL_FEATURES:
        if column in df.columns:
            values = df[column].astype("object")
            df[column] = values.where(pd.notna(values), "Unknown").astype(str)
    return df


def is_safe_diff_feature(column: str) -> bool:
    lower = column.lower()
    if not lower.endswith("_diff"):
        return False
    if column in LEAKAGE_EXACT_COLUMNS:
        return False
    return not any(token in lower for token in LEAKAGE_SUBSTRINGS)


def build_feature_sets(df: pd.DataFrame) -> tuple[list[str], list[str]]:
    numeric_features = sorted(
        column
        for column in df.columns
        if is_safe_diff_feature(column) and pd.api.types.is_numeric_dtype(df[column])
    )
    for required in ["elo_diff", "division_elo_diff"]:
        if required in df.columns and required not in numeric_features:
            numeric_features.append(required)

    categorical_features = [column for column in CATEGORICAL_FEATURES if column in df.columns]
    if not numeric_features and not categorical_features:
        raise ValueError("No leakage-safe baseline feature columns found")
    return numeric_features, categorical_features


def build_feature_sets_for_model_version(
    df: pd.DataFrame,
    model_version: str | None = None,
) -> tuple[list[str], list[str]]:
    config = get_model_config(model_version)
    missing_numeric, missing_categorical = validate_model_features(set(df.columns), config.model_version)
    if missing_numeric or missing_categorical:
        missing = missing_numeric + missing_categorical
        raise ValueError(
            f"Training data is missing {config.model_version} feature columns: {missing}"
        )
    return list(config.numeric_features), list(config.categorical_features)


def _one_hot_encoder() -> OneHotEncoder:
    try:
        return OneHotEncoder(handle_unknown="ignore", sparse_output=True)
    except TypeError:
        return OneHotEncoder(handle_unknown="ignore", sparse=True)


def calibration_cv(y_train, requested=5):
    counts = pd.Series(y_train).value_counts()
    if counts.empty:
        return None
    min_class_count = int(counts.min())
    if min_class_count >= 5:
        return min(requested, 5)
    if min_class_count >= 3:
        return 3
    if min_class_count >= 2:
        return 2
    return None


def build_ensemble_cv(y_train):
    counts = pd.Series(y_train).value_counts()
    if counts.empty:
        return None
    min_class_count = int(counts.min())
    if min_class_count >= 5:
        return StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    if min_class_count >= 3:
        return StratifiedKFold(n_splits=3, shuffle=True, random_state=42)
    if min_class_count >= 2:
        return StratifiedKFold(n_splits=2, shuffle=True, random_state=42)
    return None


def compute_model_weights(pipelines, X_train, y_train):
    cv = build_ensemble_cv(y_train)
    if cv is None:
        return {name: 1.0 / len(pipelines) for name in pipelines}

    weights = {}
    for name, pipeline in pipelines.items():
        try:
            scores = cross_val_score(
                pipeline,
                X_train,
                y_train,
                scoring="neg_log_loss",
                cv=cv,
                n_jobs=-1,
                error_score="raise",
            )
            loss = -float(np.mean(scores))
            weights[name] = 1.0 / loss if loss > 0 else 1.0
        except Exception:
            weights[name] = 1.0

    total = sum(weights.values())
    if not np.isfinite(total) or total <= 0:
        return {name: 1.0 / len(pipelines) for name in pipelines}
    return {name: weight / total for name, weight in weights.items()}


def make_calibrated(model, y_train, method="sigmoid"):
    cv = calibration_cv(y_train, requested=5)
    if cv is None:
        return model
    return CalibratedClassifierCV(model, method=method, cv=cv)


def build_ensemble_base_pipelines(
    numeric_features: list[str],
    categorical_features: list[str],
    *,
    logistic_c: float = 1.0,
    random_forest_estimators: int = 250,
    random_state: int = 42,
    y_train: pd.Series | np.ndarray | None = None,
) -> dict[str, Pipeline]:
    logistic = LogisticRegression(
        max_iter=2000,
        solver="lbfgs",
        class_weight="balanced",
        C=float(logistic_c),
    )
    rf = RandomForestClassifier(
        n_estimators=random_forest_estimators,
        min_samples_leaf=5,
        random_state=random_state,
        n_jobs=-1,
        class_weight="balanced_subsample",
    )
    gb = GradientBoostingClassifier(
        random_state=random_state,
        n_estimators=150,
        learning_rate=0.03,
        max_depth=2,
        subsample=0.80,
    )

    if y_train is not None:
        logistic = make_calibrated(logistic, y_train, method="sigmoid")
        rf = make_calibrated(rf, y_train, method="sigmoid")
        gb = make_calibrated(gb, y_train, method="sigmoid")

    return {
        "gb_shallow_primary": Pipeline(
            [
                (
                    "preprocess",
                    build_preprocessor(numeric_features, categorical_features, scale_numeric=True),
                ),
                ("model", gb),
            ]
        ),
        "cal_rf_sigmoid_challenger": Pipeline(
            [
                (
                    "preprocess",
                    build_preprocessor(numeric_features, categorical_features, scale_numeric=False),
                ),
                ("model", rf),
            ]
        ),
        "logistic_c025_sanity": Pipeline(
            [
                (
                    "preprocess",
                    build_preprocessor(numeric_features, categorical_features, scale_numeric=True),
                ),
                ("model", logistic),
            ]
        ),
    }


def build_preprocessor(
    numeric_features: list[str],
    categorical_features: list[str],
    *,
    scale_numeric: bool,
) -> ColumnTransformer:
    transformers: list[tuple[str, Pipeline, list[str]]] = []
    numeric_steps: list[tuple[str, Any]] = [("imputer", SimpleImputer(strategy="median"))]
    if scale_numeric:
        numeric_steps.append(("scaler", StandardScaler()))
    if numeric_features:
        transformers.append(("numeric", Pipeline(numeric_steps), numeric_features))
    if categorical_features:
        transformers.append(
            (
                "categorical",
                Pipeline(
                    [
                        ("imputer", SimpleImputer(strategy="most_frequent")),
                        ("onehot", _one_hot_encoder()),
                    ]
                ),
                categorical_features,
            )
        )
    return ColumnTransformer(transformers=transformers, remainder="drop")


def build_model_pipeline(
    model_name: str,
    numeric_features: list[str],
    categorical_features: list[str],
    *,
    logistic_c: float = 1.0,
    random_forest_estimators: int = 250,
    random_state: int = 42,
    y_train: pd.Series | np.ndarray | None = None,
    ensemble_weights: dict[str, float] | None = None,
) -> Pipeline:
    if model_name == "logistic":
        return Pipeline(
            [
                (
                    "preprocess",
                    build_preprocessor(numeric_features, categorical_features, scale_numeric=True),
                ),
                (
                    "model",
                    LogisticRegression(
                        max_iter=2000,
                        solver="lbfgs",
                        class_weight="balanced",
                        C=float(logistic_c),
                    ),
                ),
            ]
        )
    if model_name == "random_forest":
        return Pipeline(
            [
                (
                    "preprocess",
                    build_preprocessor(numeric_features, categorical_features, scale_numeric=False),
                ),
                (
                    "model",
                    RandomForestClassifier(
                        n_estimators=random_forest_estimators,
                        min_samples_leaf=5,
                        random_state=random_state,
                        n_jobs=-1,
                        class_weight="balanced_subsample",
                    ),
                ),
            ]
        )
    if model_name == "ensemble":
        pipelines = build_ensemble_base_pipelines(
            numeric_features,
            categorical_features,
            logistic_c=logistic_c,
            random_forest_estimators=random_forest_estimators,
            random_state=random_state,
            y_train=y_train,
        )

        if ensemble_weights is None:
            ensemble_weights = {name: 1.0 / len(pipelines) for name in pipelines}

        return Pipeline(
            [
                (
                    "model",
                    VotingClassifier(
                        estimators=[(name, pipeline) for name, pipeline in pipelines.items()],
                        voting="soft",
                        weights=[ensemble_weights[name] for name in pipelines],
                        n_jobs=-1,
                    ),
                ),
            ]
        )
    raise ValueError(f"Unsupported model: {model_name}")


def canonical_row_mask(df: pd.DataFrame) -> pd.Series:
    if "row_direction" in df.columns and (df["row_direction"] == "a_minus_b").any():
        return df["row_direction"] == "a_minus_b"
    return ~df["fight_id"].duplicated()


def split_chronological_holdout(
    df: pd.DataFrame,
    holdout_start: str | pd.Timestamp,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    cutoff = pd.to_datetime(holdout_start)
    train_df = df[df["event_date"] < cutoff].copy()
    holdout_df = df[df["event_date"] >= cutoff].copy()
    overlap = sorted(set(train_df["fight_id"]).intersection(set(holdout_df["fight_id"])))
    split = {
        "holdout_start": cutoff.strftime("%Y-%m-%d"),
        "train_rows": int(len(train_df)),
        "train_unique_fights": int(train_df["fight_id"].nunique()),
        "holdout_rows": int(len(holdout_df)),
        "holdout_unique_fights": int(holdout_df["fight_id"].nunique()),
        "fight_id_overlap_count": int(len(overlap)),
        "fight_id_overlap_sample": overlap[:20],
        "train_date_min": _date_min(train_df),
        "train_date_max": _date_max(train_df),
        "holdout_date_min": _date_min(holdout_df),
        "holdout_date_max": _date_max(holdout_df),
    }
    if train_df.empty or holdout_df.empty:
        raise ValueError(f"Empty train or holdout split: {split}")
    if overlap:
        raise ValueError(f"Grouped split failed; fight_ids crossed split: {overlap[:5]}")
    return train_df, holdout_df, split


def _date_min(df: pd.DataFrame) -> str | None:
    if df.empty:
        return None
    return pd.to_datetime(df["event_date"]).min().strftime("%Y-%m-%d")


def _date_max(df: pd.DataFrame) -> str | None:
    if df.empty:
        return None
    return pd.to_datetime(df["event_date"]).max().strftime("%Y-%m-%d")


def calibration_table(
    y_true: np.ndarray | pd.Series,
    y_proba: np.ndarray | pd.Series,
    *,
    fight_ids: pd.Series | None = None,
    bucket_count: int = 10,
) -> list[dict[str, Any]]:
    frame = pd.DataFrame(
        {
            "actual": np.asarray(y_true, dtype=int),
            "probability": np.asarray(y_proba, dtype=float),
        }
    )
    if fight_ids is not None:
        frame["fight_id"] = list(fight_ids)
    bins = np.linspace(0.0, 1.0, bucket_count + 1)
    labels = [f"{bins[i]:.1f}-{bins[i + 1]:.1f}" for i in range(bucket_count)]
    frame["bucket"] = pd.cut(
        frame["probability"],
        bins=bins,
        labels=labels,
        include_lowest=True,
        right=True,
    )

    rows: list[dict[str, Any]] = []
    for bucket, group in frame.groupby("bucket", observed=False):
        if group.empty:
            continue
        rows.append(
            {
                "bucket": str(bucket),
                "samples": int(len(group)),
                "unique_fights": int(group["fight_id"].nunique()) if "fight_id" in group else int(len(group)),
                "mean_predicted_probability": float(group["probability"].mean()),
                "actual_win_rate": float(group["actual"].mean()),
                "brier": float(np.mean((group["probability"] - group["actual"]) ** 2)),
            }
        )
    return rows


def evaluate_predictions(
    y_true: np.ndarray | pd.Series,
    y_proba: np.ndarray | pd.Series,
    *,
    fight_ids: pd.Series | None = None,
    bucket_count: int = 10,
) -> dict[str, Any]:
    true = np.asarray(y_true, dtype=int)
    proba = np.clip(np.asarray(y_proba, dtype=float), 1e-6, 1.0 - 1e-6)
    pred = (proba >= 0.5).astype(int)
    unique_classes = np.unique(true)

    metrics = {
        "sample_count": int(len(true)),
        "unique_fight_count": int(pd.Series(fight_ids).nunique()) if fight_ids is not None else int(len(true)),
        "accuracy": float(accuracy_score(true, pred)),
        "balanced_accuracy": float(balanced_accuracy_score(true, pred)),
        "log_loss": float(log_loss(true, proba, labels=[0, 1])),
        "brier_score": float(brier_score_loss(true, proba)),
        "roc_auc": None,
        "calibration": calibration_table(true, proba, fight_ids=fight_ids, bucket_count=bucket_count),
    }
    if len(unique_classes) == 2:
        metrics["roc_auc"] = float(roc_auc_score(true, proba))
    return metrics


def predict_positive_proba(model: Pipeline, df: pd.DataFrame, features: list[str]) -> np.ndarray:
    probabilities = model.predict_proba(df[features])
    classes = list(model.named_steps["model"].classes_)
    positive_index = classes.index(1)
    return probabilities[:, positive_index]


def symmetry_check(predictions: pd.DataFrame, probability_column: str) -> dict[str, Any]:
    if "row_direction" not in predictions.columns:
        return {"available": False, "reason": "row_direction column missing"}

    errors: list[float] = []
    missing_pairs = 0
    for _, group in predictions.groupby("fight_id", sort=False):
        directions = set(group["row_direction"])
        if not {"a_minus_b", "b_minus_a"}.issubset(directions):
            missing_pairs += 1
            continue
        canonical = group[group["row_direction"] == "a_minus_b"].iloc[0]
        mirror = group[group["row_direction"] == "b_minus_a"].iloc[0]
        errors.append(abs(float(canonical[probability_column]) + float(mirror[probability_column]) - 1.0))

    if not errors:
        return {
            "available": False,
            "reason": "no complete mirrored pairs",
            "missing_pairs": int(missing_pairs),
        }
    arr = np.asarray(errors, dtype=float)
    return {
        "available": True,
        "checked_pairs": int(len(errors)),
        "missing_pairs": int(missing_pairs),
        "mean_abs_probability_sum_error": float(arr.mean()),
        "median_abs_probability_sum_error": float(np.median(arr)),
        "max_abs_probability_sum_error": float(arr.max()),
        "pairs_with_error_over_0_05": int((arr > 0.05).sum()),
    }


def _json_default(value: Any) -> Any:
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        if np.isnan(value):
            return None
        return float(value)
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%d") if pd.notna(value) else None
    if pd.isna(value):
        return None
    return str(value)


def _fmt(value: Any, digits: int = 4) -> str:
    if value is None or pd.isna(value):
        return "n/a"
    if isinstance(value, (int, np.integer)):
        return str(int(value))
    if isinstance(value, (float, np.floating)):
        return f"{float(value):.{digits}f}"
    return str(value)


def _metrics_table(metrics_by_model: dict[str, dict[str, Any]], scope: str) -> str:
    lines = [
        "| model | samples | fights | accuracy | balanced accuracy | log loss | Brier | ROC AUC |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for model_name, model_metrics in metrics_by_model.items():
        metrics = model_metrics[scope]
        lines.append(
            "| "
            + " | ".join(
                [
                    model_name,
                    _fmt(metrics["sample_count"], 0),
                    _fmt(metrics["unique_fight_count"], 0),
                    _fmt(metrics["accuracy"]),
                    _fmt(metrics["balanced_accuracy"]),
                    _fmt(metrics["log_loss"]),
                    _fmt(metrics["brier_score"]),
                    _fmt(metrics["roc_auc"]),
                ]
            )
            + " |"
        )
    return "\n".join(lines)


def _calibration_markdown(calibration: list[dict[str, Any]]) -> str:
    lines = [
        "| bucket | samples | fights | mean predicted | actual win rate | Brier |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for row in calibration:
        lines.append(
            "| "
            + " | ".join(
                [
                    row["bucket"],
                    _fmt(row["samples"], 0),
                    _fmt(row["unique_fights"], 0),
                    _fmt(row["mean_predicted_probability"]),
                    _fmt(row["actual_win_rate"]),
                    _fmt(row["brier"]),
                ]
            )
            + " |"
        )
    return "\n".join(lines)


def write_report(
    path: Path,
    *,
    training_path: Path,
    model_version: str,
    feature_policy: str,
    logistic_c: float,
    shrink_factor: float,
    split: dict[str, Any],
    numeric_features: list[str],
    categorical_features: list[str],
    metrics: dict[str, dict[str, Any]],
    symmetry: dict[str, dict[str, Any]],
) -> None:
    primary_model = "logistic"
    lines = [
        "# Sprint 3 Baseline Model Report",
        "",
        "## Setup",
        "",
        f"- Training input: `{training_path}`",
        f"- Model version: `{model_version}`",
        f"- Feature policy: `{feature_policy}`",
        f"- Logistic C: `{logistic_c}`",
        f"- Registered shrink factor: `{shrink_factor}`",
        "- Training choice: mirrored rows are used for fitting; canonical `a_minus_b` rows are used for primary holdout metrics.",
        f"- Holdout start: `{split['holdout_start']}`",
        f"- Train rows/fights: {split['train_rows']} rows / {split['train_unique_fights']} fights",
        f"- Holdout rows/fights: {split['holdout_rows']} rows / {split['holdout_unique_fights']} fights",
        f"- Fight ID overlap across train/holdout: {split['fight_id_overlap_count']}",
        "",
        "## Features",
        "",
        "- Numeric: all safe numeric `_diff` columns, including Elo differentials.",
        "- Categorical: `weight_class`, `stance_matchup`, `is_catchweight_or_openweight`.",
        "- Excluded: IDs, names, outcomes, method/round/time, row direction, and post-fight/result metadata.",
        "",
        f"Numeric feature count: {len(numeric_features)}",
        "",
        f"Categorical feature count: {len(categorical_features)}",
        "",
        "## Canonical Holdout Metrics",
        "",
        _metrics_table(metrics, "canonical"),
        "",
        "## Mirrored Holdout Metrics",
        "",
        _metrics_table(metrics, "mirrored"),
        "",
        f"## Calibration ({primary_model}, Canonical Rows)",
        "",
        _calibration_markdown(metrics[primary_model]["canonical"]["calibration"]),
        "",
        "## Symmetry Check",
        "",
        "| model | pairs | mean abs error | max abs error | >0.05 errors |",
        "|---|---:|---:|---:|---:|",
    ]
    for model_name, check in symmetry.items():
        lines.append(
            "| "
            + " | ".join(
                [
                    model_name,
                    _fmt(check.get("checked_pairs"), 0),
                    _fmt(check.get("mean_abs_probability_sum_error")),
                    _fmt(check.get("max_abs_probability_sum_error")),
                    _fmt(check.get("pairs_with_error_over_0_05"), 0),
                ]
            )
            + " |"
        )

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    args = parse_args()
    config = get_model_config(args.model_version)
    training_path = resolve_training_path(args.training, config.model_version)
    out_dir = Path(args.out_dir)
    report_path = Path(args.report)
    metrics_path = Path(args.metrics_out)
    predictions_path = Path(args.predictions_out)

    df = read_training(training_path)
    numeric_features, categorical_features = build_feature_sets_for_model_version(
        df,
        config.model_version,
    )
    features = numeric_features + categorical_features
    train_df, holdout_df, split = split_chronological_holdout(df, args.holdout_start)
    canonical_holdout = holdout_df[canonical_row_mask(holdout_df)].copy()

    model_names = ["logistic"]
    if not args.skip_random_forest:
        model_names.append("random_forest")

    out_dir.mkdir(parents=True, exist_ok=True)
    predictions = holdout_df[
        [
            col
            for col in [
                "fight_id",
                "event_id",
                "event_date",
                "weight_class",
                "fighter_a",
                "fighter_b",
                TARGET_COLUMN,
                "row_direction",
            ]
            if col in holdout_df.columns
        ]
    ].copy()
    predictions["event_date"] = pd.to_datetime(predictions["event_date"]).dt.strftime("%Y-%m-%d")

    metrics: dict[str, dict[str, Any]] = {}
    symmetry: dict[str, dict[str, Any]] = {}
    saved_models: dict[str, str] = {}

    for model_name in model_names:
        model = build_model_pipeline(
            model_name,
            numeric_features,
            categorical_features,
            logistic_c=config.logistic_c if model_name == "logistic" else 1.0,
            random_forest_estimators=args.random_forest_estimators,
        )
        model.fit(train_df[features], train_df[TARGET_COLUMN])
        if model_name == "logistic":
            model_path = Path(config.model_artifact_path)
            if not model_path.is_absolute():
                model_path = out_dir / model_path.name
        else:
            model_path = out_dir / f"mens_{config.model_version}_random_forest.joblib"
        joblib.dump(model, model_path)
        saved_models[model_name] = str(model_path)
        if config.model_version == "v1_baseline":
            legacy_path = out_dir / (
                "baseline_logistic.joblib" if model_name == "logistic" else "baseline_random_forest.joblib"
            )
            if legacy_path != model_path:
                joblib.dump(model, legacy_path)
                saved_models[f"{model_name}_legacy"] = str(legacy_path)

        probability_column = f"{model_name}_prob_fighter_a_win"
        prediction_column = f"{model_name}_pred_fighter_a_win"
        holdout_proba = predict_positive_proba(model, holdout_df, features)
        canonical_proba = predict_positive_proba(model, canonical_holdout, features)
        predictions[probability_column] = holdout_proba
        predictions[prediction_column] = (holdout_proba >= 0.5).astype(int)

        metrics[model_name] = {
            "canonical": evaluate_predictions(
                canonical_holdout[TARGET_COLUMN],
                canonical_proba,
                fight_ids=canonical_holdout["fight_id"],
            ),
            "mirrored": evaluate_predictions(
                holdout_df[TARGET_COLUMN],
                holdout_proba,
                fight_ids=holdout_df["fight_id"],
            ),
        }
        symmetry[model_name] = symmetry_check(predictions, probability_column)

    predictions_path.parent.mkdir(parents=True, exist_ok=True)
    predictions.to_csv(predictions_path, index=False, encoding="utf-8-sig")

    metrics_payload = {
        "training_input": str(training_path),
        "model_version": config.model_version,
        "feature_policy": config.feature_policy,
        "model_name": config.model_name,
        "logistic_c": config.logistic_c,
        "shrink_factor": config.shrink_factor,
        "saved_models": saved_models,
        "split": split,
        "training_choice": "fit on mirrored rows; primary evaluation on canonical a_minus_b holdout rows",
        "feature_selection": {
            "numeric_features": numeric_features,
            "categorical_features": categorical_features,
            "excluded_policy": {
                "exact_columns": sorted(LEAKAGE_EXACT_COLUMNS),
                "substrings": list(LEAKAGE_SUBSTRINGS),
            },
        },
        "metrics": metrics,
        "symmetry_checks": symmetry,
    }
    metrics_path.parent.mkdir(parents=True, exist_ok=True)
    metrics_path.write_text(json.dumps(metrics_payload, indent=2, default=_json_default), encoding="utf-8")

    write_report(
        report_path,
        training_path=training_path,
        model_version=config.model_version,
        feature_policy=config.feature_policy,
        logistic_c=config.logistic_c,
        shrink_factor=config.shrink_factor,
        split=split,
        numeric_features=numeric_features,
        categorical_features=categorical_features,
        metrics=metrics,
        symmetry=symmetry,
    )
    print(json.dumps(metrics_payload, indent=2, default=_json_default))


if __name__ == "__main__":
    main()
