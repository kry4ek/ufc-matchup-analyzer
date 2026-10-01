from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


DEFAULT_MODEL_VERSION = "v3_bayes_smoothed"

BASELINE_NUMERIC_FEATURES = [
    "age_at_fight_diff",
    "avg_opponent_elo_diff",
    "career_control_seconds_per15_before_diff",
    "career_minutes_before_diff",
    "career_sapm_before_diff",
    "career_sig_str_accuracy_before_diff",
    "career_sig_str_defense_before_diff",
    "career_slpm_before_diff",
    "career_sub_attempts_per15_before_diff",
    "career_td_accuracy_before_diff",
    "career_td_avg_per15_before_diff",
    "career_td_defense_before_diff",
    "career_total_str_accuracy_before_diff",
    "career_total_str_defense_before_diff",
    "current_loss_streak_diff",
    "current_win_streak_diff",
    "days_since_elo_update_diff",
    "days_since_last_fight_diff",
    "division_elo_diff",
    "elo_diff",
    "elo_recent_trend_diff",
    "height_cm_diff",
    "last_3_sig_str_diff_per_min_diff",
    "last_3_td_diff_per15_diff",
    "last_3_win_pct_diff",
    "last_5_sig_str_diff_per_min_diff",
    "last_5_td_diff_per15_diff",
    "last_5_win_pct_diff",
    "reach_cm_diff",
    "ufc_fights_before_diff",
    "ufc_losses_before_diff",
    "ufc_win_pct_before_diff",
    "ufc_wins_before_diff",
]

BASELINE_CATEGORICAL_FEATURES = [
    "weight_class",
    "stance_matchup",
    "is_catchweight_or_openweight",
]

V2_SMOOTHED_RATE_DIFFS = [
    "sig_str_accuracy_smoothed_diff",
    "sig_str_defense_smoothed_diff",
    "td_accuracy_smoothed_diff",
    "td_defense_smoothed_diff",
    "total_str_accuracy_smoothed_diff",
    "total_str_defense_smoothed_diff",
]

V2_DEBUTANT_NUMERIC_FEATURES = [
    "fighter_a_is_ufc_debut",
    "fighter_b_is_ufc_debut",
    "both_ufc_debut",
    "one_ufc_debut",
]

V2_DEBUTANT_CATEGORICAL_FEATURES = [
    "debutant_status",
]

V3_BAYES_RATE_FAMILIES = [
    "sig_str_acc",
    "sig_str_def",
    "total_str_acc",
    "total_str_def",
    "td_acc",
    "td_def",
]

V3_BAYES_STRENGTH_SUFFIXES = [
    "s20_women_style",
    "s50_moderate",
    "current_men_v2_strength",
    "support_scaled",
]

V3_BAYES_CORE_DIFFS = [
    f"v3_bayes_{family}_{suffix}_diff"
    for suffix in V3_BAYES_STRENGTH_SUFFIXES
    for family in V3_BAYES_RATE_FAMILIES
]


@dataclass(frozen=True)
class ModelVersionConfig:
    model_version: str
    model_name: str
    logistic_c: float
    shrink_factor: float
    numeric_features: tuple[str, ...]
    categorical_features: tuple[str, ...]
    required_live_feature_groups: tuple[str, ...]
    description: str
    feature_policy: str
    default_training_path: str
    model_artifact_path: str

    @property
    def features(self) -> list[str]:
        return list(self.numeric_features) + list(self.categorical_features)


MODEL_REGISTRY: dict[str, ModelVersionConfig] = {
    "v1_baseline": ModelVersionConfig(
        model_version="v1_baseline",
        model_name="logistic",
        logistic_c=1.0,
        shrink_factor=0.90,
        numeric_features=tuple(BASELINE_NUMERIC_FEATURES),
        categorical_features=tuple(BASELINE_CATEGORICAL_FEATURES),
        required_live_feature_groups=(
            "current_baseline_prefight_snapshots",
            "elo_snapshots",
        ),
        description=(
            "Official current baseline feature policy: safe baseline numeric "
            "differentials plus weight class, stance matchup, and catch/openweight flag."
        ),
        feature_policy="current_baseline",
        default_training_path="data/processed/mens_training_rows_with_elo.csv",
        model_artifact_path="models/mens_v1_baseline.joblib",
    ),
    "v1_baseline_ensemble": ModelVersionConfig(
        model_version="v1_baseline_ensemble",
        model_name="ensemble",
        logistic_c=1.0,
        shrink_factor=0.90,
        numeric_features=tuple(BASELINE_NUMERIC_FEATURES),
        categorical_features=tuple(BASELINE_CATEGORICAL_FEATURES),
        required_live_feature_groups=(
            "current_baseline_prefight_snapshots",
            "elo_snapshots",
        ),
        description=(
            "Men's baseline ensemble variant: calibrated weighted soft-vote ensemble "
            "of shallow gradient boosting, calibrated random forest, and calibrated logistic regression."
        ),
        feature_policy="current_baseline",
        default_training_path="data/processed/mens_training_rows_with_elo.csv",
        model_artifact_path="models/mens_v1_baseline_ensemble.joblib",
    ),
    "v2_smoothed_debutant": ModelVersionConfig(
        model_version="v2_smoothed_debutant",
        model_name="logistic",
        logistic_c=0.25,
        shrink_factor=0.90,
        numeric_features=tuple(
            BASELINE_NUMERIC_FEATURES
            + V2_SMOOTHED_RATE_DIFFS
            + V2_DEBUTANT_NUMERIC_FEATURES
        ),
        categorical_features=tuple(
            BASELINE_CATEGORICAL_FEATURES + V2_DEBUTANT_CATEGORICAL_FEATURES
        ),
        required_live_feature_groups=(
            "current_baseline_prefight_snapshots",
            "elo_snapshots",
            "v2_smoothed_rates",
            "v2_debutant_flags",
        ),
        description=(
            "Sprint 15 selected v2 candidate: official baseline plus six "
            "Bayesian-smoothed rate differentials and UFC debut/no-history flags, "
            "trained with stronger logistic regularization."
        ),
        feature_policy="baseline_plus_smoothed_rates_and_debutant_flags_stronger_regularization",
        default_training_path="data/processed/mens_training_rows_v2_advanced.csv",
        model_artifact_path="models/mens_v2_smoothed_debutant.joblib",
    ),
    "v3_bayes_smoothed": ModelVersionConfig(
        model_version="v3_bayes_smoothed",
        model_name="logistic",
        logistic_c=0.10,
        shrink_factor=0.90,
        numeric_features=tuple(
            BASELINE_NUMERIC_FEATURES
            + V2_SMOOTHED_RATE_DIFFS
            + V2_DEBUTANT_NUMERIC_FEATURES
            + V3_BAYES_CORE_DIFFS
        ),
        categorical_features=tuple(
            BASELINE_CATEGORICAL_FEATURES + V2_DEBUTANT_CATEGORICAL_FEATURES
        ),
        required_live_feature_groups=(
            "current_baseline_prefight_snapshots",
            "elo_snapshots",
            "v2_smoothed_rates",
            "v2_debutant_flags",
            "v3_bayes_smoothed_rates",
        ),
        description=(
            "Promoted Sprint 52/53 candidate (experiment variant bayes_regularized_c010): "
            "v2_smoothed_debutant plus 24 prefight Bayesian-smoothed rate differentials "
            "(six rate families x four prior strengths) with C=0.10 regularization. "
            "Validated across 2024/2025/2026 development and 2022/2023 holdout windows "
            "(accuracy never below baseline, Brier improved in four of five windows); "
            "live feature parity PASS (reports/live_v3_bayes_smoothing_parity_2026.md)."
        ),
        feature_policy="v2_plus_bayes_core_diffs_c010",
        default_training_path="data/processed/mens_training_rows_v3_bayes_smoothing_candidate.csv",
        model_artifact_path="models/mens_v3_bayes_smoothed.joblib",
    ),
}

ALL_CATEGORICAL_FEATURES = tuple(
    dict.fromkeys(
        feature
        for config in MODEL_REGISTRY.values()
        for feature in config.categorical_features
    )
)


def supported_model_versions() -> list[str]:
    return list(MODEL_REGISTRY)


def get_model_config(model_version: str | None = None) -> ModelVersionConfig:
    version = model_version or DEFAULT_MODEL_VERSION
    try:
        return MODEL_REGISTRY[version]
    except KeyError as exc:
        supported = ", ".join(supported_model_versions())
        raise ValueError(f"Unsupported model version '{version}'. Supported: {supported}") from exc


def resolve_training_path(training_path: str | Path | None, model_version: str | None = None) -> Path:
    if training_path is not None and str(training_path).strip():
        return Path(training_path)
    return Path(get_model_config(model_version).default_training_path)


def validate_model_features(
    columns: list[str] | set[str],
    model_version: str | None = None,
) -> tuple[list[str], list[str]]:
    config = get_model_config(model_version)
    available = set(columns)
    missing_numeric = [feature for feature in config.numeric_features if feature not in available]
    missing_categorical = [
        feature for feature in config.categorical_features if feature not in available
    ]
    return missing_numeric, missing_categorical
