from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.features.mens_elo import EloConfig, build_mens_elo_features


SCRIPT_VERSION = "mens_advanced_features_v2_2026_05_18"


MEN_DIVISION_WEIGHTS = {
    "Flyweight": 125,
    "Bantamweight": 135,
    "Featherweight": 145,
    "Lightweight": 155,
    "Welterweight": 170,
    "Middleweight": 185,
    "Light Heavyweight": 205,
    "Heavyweight": 265,
    "Catch Weight": np.nan,
    "Open Weight": np.nan,
    "Super Heavyweight": np.nan,
}


@dataclass(frozen=True)
class RateSpec:
    base: str
    numerator: str
    denominator: str
    neutral_prior: float
    prior_strength: float
    min_division_denominator: float


RATE_SPECS = [
    RateSpec("sig_str_accuracy_smoothed", "sig_landed", "sig_attempted", 0.45, 120.0, 600.0),
    RateSpec("sig_str_defense_smoothed", "sig_defense_success", "opponent_sig_attempted", 0.55, 120.0, 600.0),
    RateSpec("td_accuracy_smoothed", "td_landed", "td_attempted", 0.35, 30.0, 90.0),
    RateSpec("td_defense_smoothed", "td_defense_success", "opponent_td_attempted", 0.65, 30.0, 90.0),
    RateSpec("total_str_accuracy_smoothed", "total_landed", "total_attempted", 0.50, 160.0, 800.0),
    RateSpec("total_str_defense_smoothed", "total_defense_success", "opponent_total_attempted", 0.50, 160.0, 800.0),
]

SMOOTHED_DIFFS = [f"{spec.base}_diff" for spec in RATE_SPECS]

METHOD_DIFFS = [
    "finish_win_rate_before_diff",
    "ko_tko_win_rate_before_diff",
    "sub_win_rate_before_diff",
    "decision_win_rate_before_diff",
    "finish_loss_rate_before_diff",
    "been_finished_rate_before_diff",
    "decision_experience_diff",
    "five_round_fight_count_before_diff",
    "five_round_minutes_before_diff",
    "five_round_win_pct_before_diff",
    "round_3_plus_experience_before_diff",
    "round_4_plus_experience_before_diff",
    "round_5_experience_before_diff",
    "late_finish_rate_before_diff",
]

AGE_LAYOFF_DIVISION_NUMERIC = [
    "age_squared_diff",
    "older_fighter_flag",
    "age_gap_abs",
    "same_layoff_bucket",
    "long_layoff_diff",
    "short_turnaround_diff",
    "changed_weight_class_diff",
]

DEBUTANT_NUMERIC = [
    "fighter_a_is_ufc_debut",
    "fighter_b_is_ufc_debut",
    "both_ufc_debut",
    "one_ufc_debut",
]

OPPONENT_QUALITY_DIFFS = [
    "avg_prior_opponent_elo_refined_diff",
    "recent_avg_opponent_elo_diff",
    "best_prior_opponent_elo_diff",
    "prior_opponent_win_pct_diff",
]

V2_DIFF_COLUMNS = SMOOTHED_DIFFS + METHOD_DIFFS + [
    "age_squared_diff",
    "long_layoff_diff",
    "short_turnaround_diff",
    "changed_weight_class_diff",
] + OPPONENT_QUALITY_DIFFS

V2_SYMMETRIC_COLUMNS = [
    "age_gap_abs",
    "same_layoff_bucket",
    "both_ufc_debut",
    "one_ufc_debut",
]

V2_MATCHUP_COLUMNS = [
    "layoff_bucket_matchup",
    "prime_age_matchup_bucket",
    "weight_class_movement_matchup",
]

V2_CATEGORICAL_COLUMNS = [
    "fighter_a_layoff_bucket",
    "fighter_b_layoff_bucket",
    "layoff_bucket_matchup",
    "fighter_a_prime_age_bucket",
    "fighter_b_prime_age_bucket",
    "prime_age_matchup_bucket",
    "fighter_a_prev_weight_class",
    "fighter_b_prev_weight_class",
    "fighter_a_weight_class_movement",
    "fighter_b_weight_class_movement",
    "weight_class_movement_matchup",
    "debutant_status",
]

V2_FEATURE_GROUPS = {
    "smoothed_rates": SMOOTHED_DIFFS,
    "method_experience": METHOD_DIFFS,
    "age_layoff_division_numeric": AGE_LAYOFF_DIVISION_NUMERIC,
    "debutant_numeric": DEBUTANT_NUMERIC,
    "opponent_quality": OPPONENT_QUALITY_DIFFS,
    "categorical": V2_CATEGORICAL_COLUMNS,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build leakage-safe advanced v2 features for the men's UFC model.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--training", default="data/processed/mens_training_rows_with_elo.csv")
    parser.add_argument("--raw-dir", default="data/raw/ufcstats_men")
    parser.add_argument("--out", default="data/processed/mens_training_rows_v2_advanced.csv")
    parser.add_argument("--audit-out", default="data/processed/mens_v2_feature_audit.json")
    parser.add_argument(
        "--completeness-out",
        default="data/processed/mens_v2_feature_completeness.csv",
    )
    return parser.parse_args()


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(path)
    return pd.read_csv(path)


def _json_default(value: Any) -> Any:
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if np.isnan(value) else float(value)
    if isinstance(value, (np.ndarray,)):
        return value.tolist()
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%d") if pd.notna(value) else None
    if pd.isna(value):
        return None
    return str(value)


def _clean_id(value: Any) -> str:
    return "" if pd.isna(value) else str(value).strip()


def _clean_text(value: Any) -> str:
    return "" if pd.isna(value) else str(value).strip()


def _num(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    try:
        if pd.isna(value):
            return default
    except (TypeError, ValueError):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def safe_div(num: float, den: float, default: float = np.nan) -> float:
    if pd.isna(num) or pd.isna(den) or float(den) == 0.0:
        return default
    return float(num) / float(den)


def clipped_rate(num: float, den: float, fallback: float) -> float:
    value = safe_div(num, den, fallback)
    if pd.isna(value) or not np.isfinite(value):
        value = fallback
    return float(min(max(value, 0.0), 1.0))


def method_category(method: Any) -> str:
    text = _clean_text(method).upper()
    if not text:
        return "other"
    if "SUB" in text:
        return "sub"
    if "KO" in text or "TKO" in text:
        return "ko_tko"
    if "DEC" in text:
        return "decision"
    return "other"


def is_finish(method: Any) -> bool:
    return method_category(method) in {"ko_tko", "sub"}


def division_weight(weight_class: Any) -> float:
    return MEN_DIVISION_WEIGHTS.get(_clean_text(weight_class), np.nan)


def weight_class_movement(previous: Any, current: Any) -> str:
    previous_text = _clean_text(previous)
    current_text = _clean_text(current)
    if not previous_text:
        return "debut_or_unknown"
    prev_weight = division_weight(previous_text)
    current_weight = division_weight(current_text)
    if pd.isna(prev_weight) or pd.isna(current_weight):
        if previous_text == current_text:
            return "same"
        return "changed_unknown_direction"
    diff = float(current_weight) - float(prev_weight)
    if diff > 0:
        return "up"
    if diff < 0:
        return "down"
    return "same"


def layoff_bucket(days: Any) -> str:
    value = _num(days, default=np.nan)
    if pd.isna(value):
        return "ufc_debut_or_unknown"
    value = float(value)
    if value <= 90:
        return "short_turnaround_0_90"
    if value <= 180:
        return "active_91_180"
    if value <= 365:
        return "standard_181_365"
    if value <= 730:
        return "long_366_730"
    return "extended_731_plus"


def prime_age_bucket(age: Any) -> str:
    value = _num(age, default=np.nan)
    if pd.isna(value):
        return "unknown_age"
    value = float(value)
    if value < 25:
        return "under_25"
    if value <= 34:
        return "prime_25_34"
    if value <= 39:
        return "veteran_35_39"
    return "over_39"


def matchup_value(a_value: Any, b_value: Any) -> str:
    return f"{_clean_text(a_value) or 'unknown'}_vs_{_clean_text(b_value) or 'unknown'}"


def reverse_matchup(value: Any) -> str:
    text = _clean_text(value)
    if "_vs_" not in text:
        return text
    left, right = text.split("_vs_", 1)
    return f"{right}_vs_{left}"


def debutant_status(a_debut: Any, b_debut: Any) -> str:
    a = bool(_num(a_debut))
    b = bool(_num(b_debut))
    if a and b:
        return "both_debutants"
    if a:
        return "fighter_a_debutant_only"
    if b:
        return "fighter_b_debutant_only"
    return "both_have_ufc_history"


def reverse_debutant_status(status: Any) -> str:
    text = _clean_text(status)
    if text == "fighter_a_debutant_only":
        return "fighter_b_debutant_only"
    if text == "fighter_b_debutant_only":
        return "fighter_a_debutant_only"
    return text


def add_opponent_stats(stats_df: pd.DataFrame) -> pd.DataFrame:
    df = stats_df.copy()
    stat_columns = [
        "significant_strikes_landed",
        "significant_strikes_attempted",
        "total_strikes_landed",
        "total_strikes_attempted",
        "takedowns_landed",
        "takedowns_attempted",
        "submission_attempts",
        "control_time_seconds",
    ]
    for col in stat_columns + ["elapsed_seconds", "won"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    keep = ["fight_id", "fighter_id"] + [col for col in stat_columns if col in df.columns]
    opponent = df[keep].copy()
    opponent = opponent.rename(
        columns={
            "fighter_id": "opponent_id",
            **{col: f"opponent_{col}" for col in keep if col not in {"fight_id", "fighter_id"}},
        }
    )
    return df.merge(opponent, on=["fight_id", "opponent_id"], how="left", validate="many_to_one")


def normalize_stats(fight_stats: pd.DataFrame, fights: pd.DataFrame) -> pd.DataFrame:
    required_stats = {
        "fight_id",
        "event_id",
        "event_date",
        "fighter_id",
        "fighter_name",
        "opponent_id",
        "opponent_name",
        "result",
        "won",
    }
    required_fights = {
        "fight_id",
        "event_id",
        "event_date",
        "weight_class",
        "method",
        "round",
        "time",
        "time_format",
    }
    missing_stats = sorted(required_stats - set(fight_stats.columns))
    missing_fights = sorted(required_fights - set(fights.columns))
    if missing_stats:
        raise ValueError(f"Missing fight_stats columns: {missing_stats}")
    if missing_fights:
        raise ValueError(f"Missing fights columns: {missing_fights}")

    stats = add_opponent_stats(fight_stats)
    meta = fights[
        [
            "fight_id",
            "event_id",
            "event_date",
            "weight_class",
            "is_catchweight_or_openweight",
            "method",
            "round",
            "time",
            "time_format",
        ]
    ].copy()
    stats = stats.merge(meta, on=["fight_id", "event_id", "event_date"], how="left", validate="many_to_one")
    stats["event_date"] = pd.to_datetime(stats["event_date"], errors="coerce")
    stats = stats[pd.notna(stats["event_date"])].copy()
    numeric_cols = [
        "won",
        "knockdowns",
        "significant_strikes_landed",
        "significant_strikes_attempted",
        "total_strikes_landed",
        "total_strikes_attempted",
        "takedowns_landed",
        "takedowns_attempted",
        "submission_attempts",
        "control_time_seconds",
        "elapsed_seconds",
        "opponent_significant_strikes_landed",
        "opponent_significant_strikes_attempted",
        "opponent_total_strikes_landed",
        "opponent_total_strikes_attempted",
        "opponent_takedowns_landed",
        "opponent_takedowns_attempted",
        "opponent_control_time_seconds",
        "round",
    ]
    for col in numeric_cols:
        if col not in stats.columns:
            stats[col] = 0.0
        stats[col] = pd.to_numeric(stats[col], errors="coerce").fillna(0.0)

    stats["method_category"] = stats["method"].map(method_category)
    stats["is_finish"] = stats["method"].map(is_finish)
    stats["scheduled_five_round"] = stats["time_format"].astype(str).str.contains(
        "5 Rnd", case=False, na=False
    )
    stats["minutes"] = stats["elapsed_seconds"] / 60.0
    stats["division_weight"] = stats["weight_class"].map(division_weight)
    return stats.sort_values(["event_date", "event_id", "fight_id", "fighter_id"], kind="mergesort").reset_index(drop=True)


def _zero_history() -> dict[str, Any]:
    return {
        "fights": 0,
        "wins": 0,
        "losses": 0,
        "finish_wins": 0,
        "ko_tko_wins": 0,
        "sub_wins": 0,
        "decision_wins": 0,
        "finish_losses": 0,
        "decision_fights": 0,
        "five_round_fights": 0,
        "five_round_minutes": 0.0,
        "five_round_wins": 0,
        "round_3_plus": 0,
        "round_4_plus": 0,
        "round_5": 0,
        "late_finishes": 0,
        "last_fight_date": pd.NaT,
        "last_weight_class": "",
        "history_max_event_date_before": pd.NaT,
        "opponent_elos": [],
        "recent_opponent_elos": deque(maxlen=3),
        "opponent_win_pcts": [],
        "sig_landed": 0.0,
        "sig_attempted": 0.0,
        "sig_defense_success": 0.0,
        "opponent_sig_attempted": 0.0,
        "td_landed": 0.0,
        "td_attempted": 0.0,
        "td_defense_success": 0.0,
        "opponent_td_attempted": 0.0,
        "total_landed": 0.0,
        "total_attempted": 0.0,
        "total_defense_success": 0.0,
        "opponent_total_attempted": 0.0,
    }


def _zero_rate_totals() -> dict[str, dict[str, float]]:
    return {spec.base: {"num": 0.0, "den": 0.0} for spec in RATE_SPECS}


def _valid_rate_parts(num: float, den: float) -> tuple[float, float] | None:
    num = float(num)
    den = float(den)
    if not np.isfinite(num) or not np.isfinite(den) or den <= 0.0 or num < 0.0:
        return None
    if num > den:
        return None
    return num, den


def _rate_parts_from_row(row: pd.Series) -> dict[str, tuple[float, float]]:
    raw = {
        "sig_str_accuracy_smoothed": (
            _num(row.get("significant_strikes_landed")),
            _num(row.get("significant_strikes_attempted")),
        ),
        "sig_str_defense_smoothed": (
            _num(row.get("opponent_significant_strikes_attempted"))
            - _num(row.get("opponent_significant_strikes_landed")),
            _num(row.get("opponent_significant_strikes_attempted")),
        ),
        "td_accuracy_smoothed": (_num(row.get("takedowns_landed")), _num(row.get("takedowns_attempted"))),
        "td_defense_smoothed": (
            _num(row.get("opponent_takedowns_attempted")) - _num(row.get("opponent_takedowns_landed")),
            _num(row.get("opponent_takedowns_attempted")),
        ),
        "total_str_accuracy_smoothed": (
            _num(row.get("total_strikes_landed")),
            _num(row.get("total_strikes_attempted")),
        ),
        "total_str_defense_smoothed": (
            _num(row.get("opponent_total_strikes_attempted")) - _num(row.get("opponent_total_strikes_landed")),
            _num(row.get("opponent_total_strikes_attempted")),
        ),
    }
    out: dict[str, tuple[float, float]] = {}
    for base, (num, den) in raw.items():
        parts = _valid_rate_parts(num, den)
        if parts is not None:
            out[base] = parts
    return out


def _choose_prior(
    spec: RateSpec,
    global_totals: dict[str, dict[str, float]],
    division_totals: dict[str, dict[str, dict[str, float]]],
    weight_class: Any,
) -> tuple[float, str, float]:
    weight_class_text = _clean_text(weight_class)
    global_parts = global_totals[spec.base]
    global_prior = clipped_rate(global_parts["num"], global_parts["den"], spec.neutral_prior)
    division_parts = division_totals.get(weight_class_text, {}).get(spec.base, {"num": 0.0, "den": 0.0})
    if division_parts["den"] >= spec.min_division_denominator:
        return clipped_rate(division_parts["num"], division_parts["den"], global_prior), "division", division_parts["den"]
    if global_parts["den"] > 0:
        return global_prior, "global", global_parts["den"]
    return float(spec.neutral_prior), "neutral", 0.0


def _smoothed_rates(
    history: dict[str, Any],
    global_totals: dict[str, dict[str, float]],
    division_totals: dict[str, dict[str, dict[str, float]]],
    weight_class: Any,
) -> dict[str, float]:
    out: dict[str, float] = {}
    for spec in RATE_SPECS:
        prior, prior_source, prior_den = _choose_prior(spec, global_totals, division_totals, weight_class)
        num = float(history.get(spec.numerator, 0.0))
        den = float(history.get(spec.denominator, 0.0))
        smoothed = (num + spec.prior_strength * prior) / (den + spec.prior_strength)
        out[spec.base] = float(min(max(smoothed, 0.0), 1.0))
        out[f"{spec.base}_support_before"] = float(den)
        out[f"{spec.base}_prior_rate_before"] = float(prior)
        out[f"{spec.base}_prior_source_before"] = prior_source
        out[f"{spec.base}_prior_den_before"] = float(prior_den)
    return out


def _fighter_snapshot(
    row: pd.Series,
    history: dict[str, Any],
    global_totals: dict[str, dict[str, float]],
    division_totals: dict[str, dict[str, dict[str, float]]],
) -> dict[str, Any]:
    event_date = pd.to_datetime(row.get("event_date"), errors="coerce")
    last_fight = pd.to_datetime(history.get("last_fight_date"), errors="coerce")
    days_since_last = (event_date - last_fight).days if pd.notna(event_date) and pd.notna(last_fight) else np.nan
    fights = int(history["fights"])
    wins = int(history["wins"])
    losses = int(history["losses"])
    completed = wins + losses
    previous_weight = history.get("last_weight_class") or ""
    current_weight = row.get("weight_class")
    movement = weight_class_movement(previous_weight, current_weight)
    changed = 1 if previous_weight and _clean_text(previous_weight) != _clean_text(current_weight) else 0
    opponent_elos = [float(x) for x in history.get("opponent_elos", []) if pd.notna(x)]
    recent_opponent_elos = [float(x) for x in list(history.get("recent_opponent_elos", [])) if pd.notna(x)]
    opponent_win_pcts = [float(x) for x in history.get("opponent_win_pcts", []) if pd.notna(x)]

    snap: dict[str, Any] = {
        "fight_id": row.get("fight_id"),
        "fighter_id": _clean_id(row.get("fighter_id")),
        "v2_history_max_event_date_before": history.get("history_max_event_date_before"),
        "ufc_win_pct_before": safe_div(wins, completed),
        "ufc_debut": 1 if fights == 0 else 0,
        "finish_win_rate_before": safe_div(history["finish_wins"], wins),
        "ko_tko_win_rate_before": safe_div(history["ko_tko_wins"], wins),
        "sub_win_rate_before": safe_div(history["sub_wins"], wins),
        "decision_win_rate_before": safe_div(history["decision_wins"], wins),
        "finish_loss_rate_before": safe_div(history["finish_losses"], losses),
        "been_finished_rate_before": safe_div(history["finish_losses"], completed),
        "decision_experience": int(history["decision_fights"]),
        "five_round_fight_count_before": int(history["five_round_fights"]),
        "five_round_minutes_before": float(history["five_round_minutes"]),
        "five_round_win_pct_before": safe_div(history["five_round_wins"], history["five_round_fights"]),
        "round_3_plus_experience_before": int(history["round_3_plus"]),
        "round_4_plus_experience_before": int(history["round_4_plus"]),
        "round_5_experience_before": int(history["round_5"]),
        "late_finish_rate_before": safe_div(history["late_finishes"], completed),
        "layoff_bucket": layoff_bucket(days_since_last),
        "long_layoff_flag": 1 if pd.notna(days_since_last) and float(days_since_last) > 365.0 else 0,
        "short_turnaround_flag": 1 if pd.notna(days_since_last) and float(days_since_last) <= 90.0 else 0,
        "prev_weight_class": previous_weight,
        "changed_weight_class": changed,
        "weight_class_movement": movement,
        "avg_prior_opponent_elo_refined": float(np.mean(opponent_elos)) if opponent_elos else np.nan,
        "recent_avg_opponent_elo": float(np.mean(recent_opponent_elos)) if recent_opponent_elos else np.nan,
        "best_prior_opponent_elo": float(np.max(opponent_elos)) if opponent_elos else np.nan,
        "prior_opponent_win_pct": float(np.mean(opponent_win_pcts)) if opponent_win_pcts else np.nan,
    }
    snap.update(_smoothed_rates(history, global_totals, division_totals, row.get("weight_class")))
    return snap


def _update_history(
    history: dict[str, Any],
    row: pd.Series,
    *,
    opponent_elo_before: float,
    opponent_win_pct_before: float,
) -> None:
    result = _clean_text(row.get("result")).lower()
    won = row.get("won")
    event_date = pd.to_datetime(row.get("event_date"), errors="coerce")
    method_cat = method_category(row.get("method"))
    finish = is_finish(row.get("method"))
    round_value = _num(row.get("round"))
    minutes = max(_num(row.get("minutes")), 0.0)

    if result == "win" or _num(won, default=np.nan) == 1.0:
        history["wins"] += 1
        if finish:
            history["finish_wins"] += 1
        if method_cat == "ko_tko":
            history["ko_tko_wins"] += 1
        if method_cat == "sub":
            history["sub_wins"] += 1
        if method_cat == "decision":
            history["decision_wins"] += 1
    elif result == "loss" or _num(won, default=np.nan) == 0.0:
        history["losses"] += 1
        if finish:
            history["finish_losses"] += 1

    if method_cat == "decision":
        history["decision_fights"] += 1
    if bool(row.get("scheduled_five_round")):
        history["five_round_fights"] += 1
        history["five_round_minutes"] += minutes
        if result == "win" or _num(won, default=np.nan) == 1.0:
            history["five_round_wins"] += 1
    if round_value >= 3:
        history["round_3_plus"] += 1
    if round_value >= 4:
        history["round_4_plus"] += 1
    if round_value >= 5:
        history["round_5"] += 1
    if finish and round_value >= 3:
        history["late_finishes"] += 1

    for base, (num, den) in _rate_parts_from_row(row).items():
        spec = next(item for item in RATE_SPECS if item.base == base)
        history[spec.numerator] += num
        history[spec.denominator] += den

    if pd.notna(opponent_elo_before):
        history["opponent_elos"].append(float(opponent_elo_before))
        history["recent_opponent_elos"].append(float(opponent_elo_before))
    if pd.notna(opponent_win_pct_before):
        history["opponent_win_pcts"].append(float(opponent_win_pct_before))
    if pd.notna(event_date):
        history["last_fight_date"] = event_date
        history["history_max_event_date_before"] = event_date
    history["last_weight_class"] = _clean_text(row.get("weight_class"))
    history["fights"] += 1


def _update_rate_totals(
    row: pd.Series,
    global_totals: dict[str, dict[str, float]],
    division_totals: dict[str, dict[str, dict[str, float]]],
) -> None:
    weight_class = _clean_text(row.get("weight_class"))
    if weight_class not in division_totals:
        division_totals[weight_class] = _zero_rate_totals()
    for base, (num, den) in _rate_parts_from_row(row).items():
        global_totals[base]["num"] += num
        global_totals[base]["den"] += den
        division_totals[weight_class][base]["num"] += num
        division_totals[weight_class][base]["den"] += den


def build_elo_lookup(fights: pd.DataFrame) -> dict[tuple[str, str], float]:
    snapshots, _ = build_mens_elo_features(fights, config=EloConfig())
    lookup: dict[tuple[str, str], float] = {}
    if snapshots.empty:
        return lookup
    for _, row in snapshots.iterrows():
        lookup[(_clean_id(row.get("fight_id")), _clean_id(row.get("fighter_id")))] = _num(
            row.get("elo_before"), default=np.nan
        )
    return lookup


def build_advanced_snapshots(stats: pd.DataFrame, fights: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    elo_lookup = build_elo_lookup(fights)
    histories: dict[str, dict[str, Any]] = defaultdict(_zero_history)
    global_totals = _zero_rate_totals()
    division_totals: dict[str, dict[str, dict[str, float]]] = {}
    snapshots: list[dict[str, Any]] = []
    invalid_rate_rows = 0

    for event_date, date_group in stats.groupby("event_date", sort=True, dropna=False):
        date_snapshots: dict[tuple[str, str], dict[str, Any]] = {}
        for _, row in date_group.iterrows():
            fighter_id = _clean_id(row.get("fighter_id"))
            if not fighter_id:
                continue
            parts = _rate_parts_from_row(row)
            if len(parts) < len(RATE_SPECS):
                invalid_rate_rows += 1
            snap = _fighter_snapshot(row, histories[fighter_id], global_totals, division_totals)
            date_snapshots[(_clean_id(row.get("fight_id")), fighter_id)] = snap
            snapshots.append(snap)

        for _, row in date_group.iterrows():
            fighter_id = _clean_id(row.get("fighter_id"))
            opponent_id = _clean_id(row.get("opponent_id"))
            if not fighter_id:
                continue
            opponent_snap = date_snapshots.get((_clean_id(row.get("fight_id")), opponent_id), {})
            opponent_elo = elo_lookup.get((_clean_id(row.get("fight_id")), opponent_id), np.nan)
            _update_history(
                histories[fighter_id],
                row,
                opponent_elo_before=opponent_elo,
                opponent_win_pct_before=_num(opponent_snap.get("ufc_win_pct_before"), default=np.nan),
            )
            _update_rate_totals(row, global_totals, division_totals)

    snapshots_df = pd.DataFrame(snapshots)
    audit = {
        "snapshot_rows": int(len(snapshots_df)),
        "unique_snapshot_fights": int(snapshots_df["fight_id"].nunique()) if "fight_id" in snapshots_df else 0,
        "invalid_or_zero_denominator_rate_rows": int(invalid_rate_rows),
        "elo_lookup_rows": int(len(elo_lookup)),
        "rate_prior_policy": {
            "time_varying": True,
            "cutoff": "event_date strictly before current event date; same-date fights do not update each other",
            "division_prior_policy": "use same-division prior only after the configured minimum denominator, otherwise global prior, otherwise neutral prior",
            "rate_specs": [spec.__dict__ for spec in RATE_SPECS],
        },
    }
    return snapshots_df, audit


def _prefixed_snapshots(snapshots: pd.DataFrame, side: str) -> pd.DataFrame:
    id_col = f"fighter_{side}_id"
    out = snapshots.copy()
    out = out.rename(columns={"fighter_id": id_col})
    rename: dict[str, str] = {}
    for col in out.columns:
        if col in {"fight_id", id_col}:
            continue
        rename[col] = f"fighter_{side}_{col}"
    return out.rename(columns=rename)


def add_pair_features(training: pd.DataFrame, snapshots: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    required = {"fight_id", "fighter_a_id", "fighter_b_id", "event_date"}
    missing = sorted(required - set(training.columns))
    if missing:
        raise ValueError(f"Missing training columns: {missing}")

    out = training.copy()
    before_cols = set(out.columns)
    out["fight_id"] = out["fight_id"].astype(str)
    out["fighter_a_id"] = out["fighter_a_id"].astype(str)
    out["fighter_b_id"] = out["fighter_b_id"].astype(str)
    snapshots = snapshots.copy()
    snapshots["fight_id"] = snapshots["fight_id"].astype(str)
    snapshots["fighter_id"] = snapshots["fighter_id"].astype(str)

    out = out.merge(_prefixed_snapshots(snapshots, "a"), on=["fight_id", "fighter_a_id"], how="left", validate="many_to_one")
    out = out.merge(_prefixed_snapshots(snapshots, "b"), on=["fight_id", "fighter_b_id"], how="left", validate="many_to_one")

    side_bases = [
        spec.base
        for spec in RATE_SPECS
    ] + [
        "finish_win_rate_before",
        "ko_tko_win_rate_before",
        "sub_win_rate_before",
        "decision_win_rate_before",
        "finish_loss_rate_before",
        "been_finished_rate_before",
        "decision_experience",
        "five_round_fight_count_before",
        "five_round_minutes_before",
        "five_round_win_pct_before",
        "round_3_plus_experience_before",
        "round_4_plus_experience_before",
        "round_5_experience_before",
        "late_finish_rate_before",
        "long_layoff_flag",
        "short_turnaround_flag",
        "changed_weight_class",
        "avg_prior_opponent_elo_refined",
        "recent_avg_opponent_elo",
        "best_prior_opponent_elo",
        "prior_opponent_win_pct",
    ]
    diff_names = {
        "finish_win_rate_before": "finish_win_rate_before_diff",
        "ko_tko_win_rate_before": "ko_tko_win_rate_before_diff",
        "sub_win_rate_before": "sub_win_rate_before_diff",
        "decision_win_rate_before": "decision_win_rate_before_diff",
        "finish_loss_rate_before": "finish_loss_rate_before_diff",
        "been_finished_rate_before": "been_finished_rate_before_diff",
        "decision_experience": "decision_experience_diff",
        "five_round_fight_count_before": "five_round_fight_count_before_diff",
        "five_round_minutes_before": "five_round_minutes_before_diff",
        "five_round_win_pct_before": "five_round_win_pct_before_diff",
        "round_3_plus_experience_before": "round_3_plus_experience_before_diff",
        "round_4_plus_experience_before": "round_4_plus_experience_before_diff",
        "round_5_experience_before": "round_5_experience_before_diff",
        "late_finish_rate_before": "late_finish_rate_before_diff",
        "long_layoff_flag": "long_layoff_diff",
        "short_turnaround_flag": "short_turnaround_diff",
        "changed_weight_class": "changed_weight_class_diff",
        "avg_prior_opponent_elo_refined": "avg_prior_opponent_elo_refined_diff",
        "recent_avg_opponent_elo": "recent_avg_opponent_elo_diff",
        "best_prior_opponent_elo": "best_prior_opponent_elo_diff",
        "prior_opponent_win_pct": "prior_opponent_win_pct_diff",
    }
    for spec in RATE_SPECS:
        diff_names[spec.base] = f"{spec.base}_diff"

    for base in side_bases:
        a_col = f"fighter_a_{base}"
        b_col = f"fighter_b_{base}"
        if a_col in out.columns and b_col in out.columns:
            out[diff_names[base]] = pd.to_numeric(out[a_col], errors="coerce") - pd.to_numeric(
                out[b_col], errors="coerce"
            )

    for side in ["a", "b"]:
        age_col = f"fighter_{side}_age_at_fight"
        if age_col in out.columns:
            age = pd.to_numeric(out[age_col], errors="coerce")
            out[f"fighter_{side}_age_squared"] = age**2
            out[f"fighter_{side}_prime_age_bucket"] = age.map(prime_age_bucket)

    if "fighter_a_age_squared" in out.columns and "fighter_b_age_squared" in out.columns:
        out["age_squared_diff"] = out["fighter_a_age_squared"] - out["fighter_b_age_squared"]
    if "fighter_a_age_at_fight" in out.columns and "fighter_b_age_at_fight" in out.columns:
        age_diff = pd.to_numeric(out["fighter_a_age_at_fight"], errors="coerce") - pd.to_numeric(
            out["fighter_b_age_at_fight"], errors="coerce"
        )
        out["older_fighter_flag"] = np.where(age_diff > 0, 1, np.where(age_diff < 0, -1, 0))
        out["age_gap_abs"] = age_diff.abs()
        out["prime_age_matchup_bucket"] = out.apply(
            lambda row: matchup_value(row.get("fighter_a_prime_age_bucket"), row.get("fighter_b_prime_age_bucket")),
            axis=1,
        )

    out["fighter_a_layoff_bucket"] = out["fighter_a_layoff_bucket"].fillna("ufc_debut_or_unknown")
    out["fighter_b_layoff_bucket"] = out["fighter_b_layoff_bucket"].fillna("ufc_debut_or_unknown")
    out["same_layoff_bucket"] = (
        out["fighter_a_layoff_bucket"].astype(str) == out["fighter_b_layoff_bucket"].astype(str)
    ).astype(int)
    out["layoff_bucket_matchup"] = out.apply(
        lambda row: matchup_value(row.get("fighter_a_layoff_bucket"), row.get("fighter_b_layoff_bucket")),
        axis=1,
    )
    out["weight_class_movement_matchup"] = out.apply(
        lambda row: matchup_value(row.get("fighter_a_weight_class_movement"), row.get("fighter_b_weight_class_movement")),
        axis=1,
    )
    out["fighter_a_is_ufc_debut"] = pd.to_numeric(out["fighter_a_ufc_debut"], errors="coerce").fillna(0).astype(int)
    out["fighter_b_is_ufc_debut"] = pd.to_numeric(out["fighter_b_ufc_debut"], errors="coerce").fillna(0).astype(int)
    out["both_ufc_debut"] = ((out["fighter_a_is_ufc_debut"] == 1) & (out["fighter_b_is_ufc_debut"] == 1)).astype(int)
    out["one_ufc_debut"] = ((out["fighter_a_is_ufc_debut"] + out["fighter_b_is_ufc_debut"]) == 1).astype(int)
    out["debutant_status"] = out.apply(
        lambda row: debutant_status(row.get("fighter_a_is_ufc_debut"), row.get("fighter_b_is_ufc_debut")),
        axis=1,
    )

    appended = [col for col in out.columns if col not in before_cols]
    return out, appended


def mirror_groups(df: pd.DataFrame):
    if "fight_id" not in df.columns or "row_direction" not in df.columns:
        return
    for fight_id, group in df.groupby("fight_id", sort=False):
        if len(group) < 2:
            continue
        canonical = group[group["row_direction"] == "a_minus_b"]
        mirror = group[group["row_direction"] == "b_minus_a"]
        if canonical.empty or mirror.empty:
            continue
        yield fight_id, canonical.iloc[0], mirror.iloc[0]


def paired_mirror_frames(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    if "fight_id" not in df.columns or "row_direction" not in df.columns:
        return pd.DataFrame(), pd.DataFrame()
    canonical = (
        df[df["row_direction"] == "a_minus_b"]
        .drop_duplicates("fight_id")
        .set_index("fight_id", drop=False)
    )
    mirror = (
        df[df["row_direction"] == "b_minus_a"]
        .drop_duplicates("fight_id")
        .set_index("fight_id", drop=False)
    )
    common = canonical.index.intersection(mirror.index)
    return canonical.loc[common].copy(), mirror.loc[common].copy()


def mirrored_sign_check(df: pd.DataFrame, columns: list[str]) -> dict[str, Any]:
    checks: dict[str, Any] = {}
    canonical, mirror = paired_mirror_frames(df)
    for col in columns:
        if col not in df.columns or canonical.empty:
            continue
        a = pd.to_numeric(canonical[col], errors="coerce")
        b = pd.to_numeric(mirror[col], errors="coerce")
        both_nan = a.isna() & b.isna()
        one_nan = a.isna() ^ b.isna()
        bad_sum = (~both_nan) & (~one_nan) & ((a + b).abs() > 1e-8)
        bad = canonical.loc[one_nan | bad_sum, ["fight_id"]].copy()
        bad["canonical"] = a.loc[bad.index]
        bad["mirror"] = b.loc[bad.index]
        bad["sum"] = (a + b).loc[bad.index]
        checks[col] = {
            "passed": bool(bad.empty),
            "checked_pairs": int((~both_nan & ~one_nan).sum()),
            "skipped_both_nan_pairs": int(both_nan.sum()),
            "violation_count": int(len(bad)),
            "violations_sample": bad.head(20).to_dict("records"),
        }
    return checks


def mirrored_symmetric_check(df: pd.DataFrame, columns: list[str]) -> dict[str, Any]:
    checks: dict[str, Any] = {}
    canonical, mirror = paired_mirror_frames(df)
    for col in columns:
        if col not in df.columns or canonical.empty:
            continue
        a = canonical[col]
        b = mirror[col]
        both_nan = a.isna() & b.isna()
        mismatch = (~both_nan) & (a.astype(str) != b.astype(str))
        bad = canonical.loc[mismatch, ["fight_id"]].copy()
        bad["canonical"] = a.loc[bad.index]
        bad["mirror"] = b.loc[bad.index]
        checks[col] = {
            "passed": bool(bad.empty),
            "checked_pairs": int((~both_nan).sum()),
            "violation_count": int(len(bad)),
            "violations_sample": bad.head(20).to_dict("records"),
        }
    return checks


def mirrored_matchup_check(df: pd.DataFrame, columns: list[str]) -> dict[str, Any]:
    checks: dict[str, Any] = {}
    canonical, mirror = paired_mirror_frames(df)
    for col in columns:
        if col not in df.columns or canonical.empty:
            continue
        expected = canonical[col].map(reverse_matchup)
        actual = mirror[col].map(_clean_text)
        mismatch = expected != actual
        bad = canonical.loc[mismatch, ["fight_id"]].copy()
        bad["expected"] = expected.loc[bad.index]
        bad["actual"] = actual.loc[bad.index]
        checks[col] = {
            "passed": bool(bad.empty),
            "checked_pairs": int(len(canonical)),
            "violation_count": int(len(bad)),
            "violations_sample": bad.head(20).to_dict("records"),
        }
    return checks


def mirrored_debutant_status_check(df: pd.DataFrame) -> dict[str, Any]:
    if "debutant_status" not in df.columns:
        return {"passed": False, "reason": "missing debutant_status"}
    canonical, mirror = paired_mirror_frames(df)
    expected = canonical["debutant_status"].map(reverse_debutant_status)
    actual = mirror["debutant_status"].map(_clean_text)
    mismatch = expected != actual
    bad = canonical.loc[mismatch, ["fight_id"]].copy()
    bad["expected"] = expected.loc[bad.index]
    bad["actual"] = actual.loc[bad.index]
    return {
        "passed": bool(bad.empty),
        "checked_pairs": int(len(canonical)),
        "violation_count": int(len(bad)),
        "violations_sample": bad.head(20).to_dict("records"),
    }


def side_swap_check(df: pd.DataFrame, base_names: list[str]) -> dict[str, Any]:
    checks: dict[str, Any] = {}
    canonical, mirror = paired_mirror_frames(df)
    for base in base_names:
        a_col = f"fighter_a_{base}"
        b_col = f"fighter_b_{base}"
        if a_col not in df.columns or b_col not in df.columns or canonical.empty:
            continue
        mismatch = (canonical[a_col].astype(str) != mirror[b_col].astype(str)) | (
            canonical[b_col].astype(str) != mirror[a_col].astype(str)
        )
        bad = canonical.loc[mismatch, ["fight_id"]].copy()
        bad["canonical_a"] = canonical.loc[bad.index, a_col]
        bad["canonical_b"] = canonical.loc[bad.index, b_col]
        bad["mirror_a"] = mirror.loc[bad.index, a_col]
        bad["mirror_b"] = mirror.loc[bad.index, b_col]
        checks[base] = {
            "passed": bool(bad.empty),
            "checked_pairs": int(len(canonical)),
            "violation_count": int(len(bad)),
            "violations_sample": bad.head(20).to_dict("records"),
        }
    return checks


def leakage_checks(df: pd.DataFrame) -> dict[str, Any]:
    checks: dict[str, Any] = {}
    event_dates = pd.to_datetime(df.get("event_date"), errors="coerce")
    for side in ["a", "b"]:
        col = f"fighter_{side}_v2_history_max_event_date_before"
        if col not in df.columns:
            continue
        prior_dates = pd.to_datetime(df[col], errors="coerce")
        bad = df[pd.notna(prior_dates) & pd.notna(event_dates) & (prior_dates >= event_dates)]
        checks[col] = {
            "passed": bool(bad.empty),
            "rows_checked_with_history": int((pd.notna(prior_dates) & pd.notna(event_dates)).sum()),
            "violation_count": int(len(bad)),
            "violations_sample": bad[["fight_id", "event_date", col]].head(20).to_dict("records"),
        }
    return checks


def build_completeness(df: pd.DataFrame, v2_columns: list[str]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    row_count = len(df)
    for col in v2_columns:
        if col not in df.columns:
            continue
        series = df[col]
        numeric = pd.to_numeric(series, errors="coerce")
        is_numeric = pd.api.types.is_numeric_dtype(series) or numeric.notna().any()
        missing = int(series.isna().sum())
        zero = int((numeric == 0).sum()) if is_numeric else 0
        rows.append(
            {
                "feature_column": col,
                "dtype": str(series.dtype),
                "is_numeric": bool(is_numeric),
                "missing_count": missing,
                "missing_percentage": missing / row_count * 100.0 if row_count else 0.0,
                "zero_count": zero,
                "zero_percentage": zero / row_count * 100.0 if row_count else 0.0,
                "min": None if not is_numeric or numeric.dropna().empty else float(numeric.min()),
                "max": None if not is_numeric or numeric.dropna().empty else float(numeric.max()),
                "mean": None if not is_numeric or numeric.dropna().empty else float(numeric.mean()),
                "unique_values": int(series.nunique(dropna=True)),
            }
        )
    return pd.DataFrame(rows).sort_values(["missing_percentage", "feature_column"], ascending=[False, True])


def rate_sanity_checks(df: pd.DataFrame, v2_columns: list[str]) -> dict[str, Any]:
    checks: dict[str, Any] = {}
    for col in v2_columns:
        if col not in df.columns:
            continue
        numeric = pd.to_numeric(df[col], errors="coerce")
        if numeric.dropna().empty:
            continue
        if col.endswith("_support_before") or col.endswith("_prior_den_before"):
            continue
        lower: float | None = None
        upper: float | None = None
        if col == "older_fighter_flag":
            lower, upper = -1.0, 1.0
        elif any(token in col for token in ["rate", "pct", "accuracy_smoothed", "defense_smoothed"]) and not col.endswith("_diff"):
            lower, upper = 0.0, 1.0
        elif col in SMOOTHED_DIFFS or col.endswith("_rate_before_diff") or col.endswith("_pct_before_diff"):
            lower, upper = -1.0, 1.0
        elif col.endswith("_flag") or col in DEBUTANT_NUMERIC + ["same_layoff_bucket"]:
            lower, upper = 0.0, 1.0
        elif col.endswith("_diff") and any(token in col for token in ["flag", "changed_weight_class", "long_layoff", "short_turnaround"]):
            lower, upper = -1.0, 1.0
        if lower is None or upper is None:
            continue
        bad = df[pd.notna(numeric) & ((numeric < lower) | (numeric > upper))]
        checks[col] = {
            "passed": bool(bad.empty),
            "expected_min": lower,
            "expected_max": upper,
            "observed_min": float(numeric.min()),
            "observed_max": float(numeric.max()),
            "violation_count": int(len(bad)),
            "violations_sample": bad[["fight_id", "row_direction", col]].head(20).to_dict("records")
            if "fight_id" in bad
            else [],
        }
    return checks


def build_audit(
    training: pd.DataFrame,
    output: pd.DataFrame,
    v2_columns: list[str],
    completeness: pd.DataFrame,
    snapshot_audit: dict[str, Any],
) -> dict[str, Any]:
    row_counts = output["row_direction"].value_counts(dropna=False).to_dict() if "row_direction" in output else {}
    missing_top = completeness.sort_values("missing_percentage", ascending=False).head(25).to_dict("records")
    zero_top = completeness.sort_values("zero_percentage", ascending=False).head(25).to_dict("records")
    changed_cols = [c for c in ["fighter_a_changed_weight_class", "fighter_b_changed_weight_class"] if c in output.columns]
    changed_counts = {
        col: int(pd.to_numeric(output[col], errors="coerce").fillna(0).sum())
        for col in changed_cols
    }
    debut_cols = [c for c in DEBUTANT_NUMERIC if c in output.columns]
    debut_counts = {
        col: int(pd.to_numeric(output[col], errors="coerce").fillna(0).sum())
        for col in debut_cols
    }
    sign_checks = mirrored_sign_check(output, [col for col in V2_DIFF_COLUMNS if col in output.columns])
    symmetric_checks = mirrored_symmetric_check(output, [col for col in V2_SYMMETRIC_COLUMNS if col in output.columns])
    matchup_checks = mirrored_matchup_check(output, [col for col in V2_MATCHUP_COLUMNS if col in output.columns])
    side_checks = side_swap_check(
        output,
        [
            "is_ufc_debut",
            "layoff_bucket",
            "prev_weight_class",
            "changed_weight_class",
            "weight_class_movement",
            "prime_age_bucket",
        ],
    )
    all_mirror_passed = all(item["passed"] for item in sign_checks.values())
    all_mirror_passed = all_mirror_passed and all(item["passed"] for item in symmetric_checks.values())
    all_mirror_passed = all_mirror_passed and all(item["passed"] for item in matchup_checks.values())
    all_mirror_passed = all_mirror_passed and mirrored_debutant_status_check(output)["passed"]

    leak = leakage_checks(output)
    sanity = rate_sanity_checks(output, v2_columns)
    return {
        "script_version": SCRIPT_VERSION,
        "input_rows": int(len(training)),
        "output_rows": int(len(output)),
        "input_columns": int(len(training.columns)),
        "output_columns": int(len(output.columns)),
        "v2_columns_added": int(len(v2_columns)),
        "unique_fights": int(output["fight_id"].nunique()) if "fight_id" in output else 0,
        "row_directions": row_counts,
        "feature_groups": V2_FEATURE_GROUPS,
        "leakage_checks": leak,
        "current_or_future_usage_check_passed": all(item["passed"] for item in leak.values()),
        "mirrored_row_checks": {
            "all_passed": bool(all_mirror_passed),
            "numeric_diff_sign": sign_checks,
            "symmetric_features": symmetric_checks,
            "matchup_categoricals": matchup_checks,
            "debutant_status": mirrored_debutant_status_check(output),
            "side_swap": side_checks,
        },
        "missingness_top": missing_top,
        "zero_rate_top": zero_top,
        "sanity_checks": sanity,
        "sanity_checks_passed": all(item["passed"] for item in sanity.values()),
        "debutant_flag_counts": debut_counts,
        "changed_weight_class_counts": changed_counts,
        "snapshot_builder": snapshot_audit,
        "limitations": [
            "Title-fight and main-event experience are not created because the raw men files do not carry reliable title/main-event metadata.",
            "Smoothed-rate priors are time-varying by event date; same-date fights are excluded from each other.",
            "Division-specific smoothed priors are used only after minimum denominator thresholds; otherwise global or neutral priors are used.",
            "Takedown/control repair is not ported as a separate repair process; the builder uses the existing parsed men's takedown and control fields.",
        ],
    }


def write_womens_reference_notes(path: Path) -> None:
    lines = [
        "# Sprint 14 Women's Advanced Feature Reference Notes",
        "",
        "Read-only reference project inspected: `E:\\ufc_fight_predictor\\womens_ufc_model`.",
        "",
        "## Feature Ideas Found",
        "",
        "- `compute_live_bayes_smoothing_features_v1.py` computes Bayesian-smoothed prefight accuracy/allowed-rate features from prior fighter rows only.",
        "- `add_advanced_features_v1.py` adds opponent Elo summaries, method/finish profiles, scheduled five-round history, late-round history, division movement, recency, and age/physical shape features.",
        "- `ufc_womens_dataset_builder\\features.py` builds leakage-safe prefight snapshots with striking, takedown, control, recent-form, age, stance, and Elo fields.",
        "- Repaired women datasets include repaired significant-strike/takedown/control inputs before smoothing.",
        "",
        "## Portable To Men Now",
        "",
        "- Bayesian-smoothed striking accuracy, striking defense, takedown accuracy, takedown defense, total-strike accuracy, and total-strike defense from men's `fight_stats.csv`.",
        "- Finish/method win/loss rates from men's `fights.csv` method/result fields.",
        "- Scheduled five-round and late-round experience from `time_format`, `round`, `time`, and `elapsed_seconds`.",
        "- Layoff buckets and short/long turnaround flags from existing prefight history dates.",
        "- Age-shape features from existing fighter date-of-birth/profile columns already present in training rows.",
        "- Division movement from each fighter's previous UFC `weight_class`.",
        "- UFC debut/no-history flags from prior fight counts.",
        "- Refined opponent quality summaries using the existing men's Elo engine and prior opponent histories.",
        "",
        "## Requires Additional Data",
        "",
        "- Main-event experience needs reliable card-order metadata. The current raw men files do not identify bout order as a stable feature.",
        "- Title-fight experience needs explicit title-bout metadata. A five-round fight is not always a title fight and should not be treated as one.",
        "- Full repaired-stat parity with the women pipeline would require a separate men-specific repair audit if parser defects are discovered.",
        "",
        "## Should Not Be Ported Yet",
        "",
        "- Betting or market/odds interpretation features. Sprint 14 is prediction-feature research only and should not add betting advice.",
        "- Paid API integrations or new scraping. This sprint uses existing local raw files only.",
        "- Automatic v2 promotion into the official men predictor or baseline. The v2 file is an experimental input for controlled backtests.",
        "",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def build_features(args: argparse.Namespace) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    training = read_csv(Path(args.training))
    raw_dir = Path(args.raw_dir)
    fights = read_csv(raw_dir / "fights.csv")
    fight_stats = read_csv(raw_dir / "fight_stats.csv")
    fighters_path = raw_dir / "fighters.csv"
    if fighters_path.exists():
        _ = read_csv(fighters_path)

    stats = normalize_stats(fight_stats, fights)
    snapshots, snapshot_audit = build_advanced_snapshots(stats, fights)
    output, v2_columns = add_pair_features(training, snapshots)
    completeness = build_completeness(output, v2_columns)
    audit = build_audit(training, output, v2_columns, completeness, snapshot_audit)
    return output, completeness, audit


def main() -> None:
    args = parse_args()
    output, completeness, audit = build_features(args)

    out_path = Path(args.out)
    audit_path = Path(args.audit_out)
    completeness_path = Path(args.completeness_out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    completeness_path.parent.mkdir(parents=True, exist_ok=True)

    output.to_csv(out_path, index=False, encoding="utf-8-sig")
    completeness.to_csv(completeness_path, index=False, encoding="utf-8-sig")
    audit_path.write_text(json.dumps(audit, indent=2, default=_json_default), encoding="utf-8")
    write_womens_reference_notes(Path("reports/sprint_14_womens_feature_reference_notes.md"))

    print(json.dumps({
        "output": str(out_path),
        "audit": str(audit_path),
        "completeness": str(completeness_path),
        "rows": audit["output_rows"],
        "v2_columns_added": audit["v2_columns_added"],
        "leakage_passed": audit["current_or_future_usage_check_passed"],
        "mirror_passed": audit["mirrored_row_checks"]["all_passed"],
    }, indent=2))


if __name__ == "__main__":
    main()
