from __future__ import annotations

import argparse
import json
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


warnings.filterwarnings("ignore", category=pd.errors.PerformanceWarning)

SCRIPT_VERSION = "mens_v3_bayes_smoothing_candidate_2026_06_12_seb"
DEFAULT_MANIFEST_OUT = Path("_update_manifests/feature_columns.csv")

TARGET_OR_POSTFIGHT_TOKENS = [
    "result",
    "won",
    "winner",
    "method",
    "finish",
    "round",
    "time",
    "ko",
    "sub",
    "decision",
    "actual",
    "correct",
    "label",
    "target",
]


@dataclass(frozen=True)
class RateFamily:
    family: str
    display_name: str
    current_v2_base: str
    prefight_rate_suffix: str
    neutral_prior: float
    current_men_v2_strength: float
    division_prior_denominator_threshold: float
    low_support_threshold: float
    numerator_note: str
    denominator_note: str


RATE_FAMILIES = [
    RateFamily(
        family="sig_str_acc",
        display_name="significant-strike accuracy",
        current_v2_base="sig_str_accuracy_smoothed",
        prefight_rate_suffix="career_sig_str_accuracy_before",
        neutral_prior=0.45,
        current_men_v2_strength=120.0,
        division_prior_denominator_threshold=600.0,
        low_support_threshold=120.0,
        numerator_note="prior significant strikes landed",
        denominator_note="prior significant strikes attempted",
    ),
    RateFamily(
        family="sig_str_def",
        display_name="significant-strike defense",
        current_v2_base="sig_str_defense_smoothed",
        prefight_rate_suffix="career_sig_str_defense_before",
        neutral_prior=0.55,
        current_men_v2_strength=120.0,
        division_prior_denominator_threshold=600.0,
        low_support_threshold=120.0,
        numerator_note="prior opponent significant-strike attempts not landed",
        denominator_note="prior opponent significant-strike attempts",
    ),
    RateFamily(
        family="total_str_acc",
        display_name="total-strike accuracy",
        current_v2_base="total_str_accuracy_smoothed",
        prefight_rate_suffix="career_total_str_accuracy_before",
        neutral_prior=0.50,
        current_men_v2_strength=160.0,
        division_prior_denominator_threshold=800.0,
        low_support_threshold=160.0,
        numerator_note="prior total strikes landed",
        denominator_note="prior total strikes attempted",
    ),
    RateFamily(
        family="total_str_def",
        display_name="total-strike defense",
        current_v2_base="total_str_defense_smoothed",
        prefight_rate_suffix="career_total_str_defense_before",
        neutral_prior=0.50,
        current_men_v2_strength=160.0,
        division_prior_denominator_threshold=800.0,
        low_support_threshold=160.0,
        numerator_note="prior opponent total-strike attempts not landed",
        denominator_note="prior opponent total-strike attempts",
    ),
    RateFamily(
        family="td_acc",
        display_name="takedown accuracy",
        current_v2_base="td_accuracy_smoothed",
        prefight_rate_suffix="career_td_accuracy_before",
        neutral_prior=0.35,
        current_men_v2_strength=30.0,
        division_prior_denominator_threshold=90.0,
        low_support_threshold=30.0,
        numerator_note="prior takedowns landed",
        denominator_note="prior takedowns attempted",
    ),
    RateFamily(
        family="td_def",
        display_name="takedown defense",
        current_v2_base="td_defense_smoothed",
        prefight_rate_suffix="career_td_defense_before",
        neutral_prior=0.65,
        current_men_v2_strength=30.0,
        division_prior_denominator_threshold=90.0,
        low_support_threshold=30.0,
        numerator_note="prior opponent takedown attempts not landed",
        denominator_note="prior opponent takedown attempts",
    ),
]

SIDE_TEMPLATE_SUFFIXES = [
    "prefight_rate_before",
    "raw_num_estimate_before",
    "denominator_before",
    "prior_mean_used",
    "global_prior_mean",
    "division_prior_mean",
    "prior_source",
    "prior_denominator",
    "s20_women_style",
    "s50_moderate",
    "current_men_v2_strength",
    "support_scaled",
    "support_scaled_strength",
    "seb",
    "seb_strength",
    "prior_only_flag",
    "low_support_flag",
]

DIFF_TEMPLATE_SUFFIXES = [
    "s20_women_style_diff",
    "s50_moderate_diff",
    "current_men_v2_strength_diff",
    "support_scaled_diff",
    "seb_diff",
    "support_diff",
    "support_min",
    "support_asymmetry_abs",
    "either_low_support_flag",
    "both_low_support_flag",
    "either_prior_only_flag",
]

# Empirical-Bayes estimated prior strength ("seb"): beta-binomial
# method-of-moments over the population of per-fighter prefight
# (numerator, denominator) totals strictly before each event date.
SEB_MIN_STRENGTH = 5.0
SEB_MAX_STRENGTH = 500.0
SEB_MIN_FIGHTERS = 30


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build a non-default men v3 Bayesian smoothing candidate file from "
            "existing prefight v2 advanced rows."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--input", default="data/processed/mens_training_rows_v2_advanced.csv")
    parser.add_argument(
        "--out",
        default="data/processed/mens_training_rows_v3_bayes_smoothing_candidate.csv",
    )
    parser.add_argument(
        "--audit-out",
        default="data/processed/mens_v3_bayes_smoothing_candidate_audit.json",
    )
    parser.add_argument(
        "--manifest-out",
        default=str(DEFAULT_MANIFEST_OUT),
        help="Feature manifest CSV. Use an empty string to skip.",
    )
    return parser.parse_args()


def json_default(value: Any) -> Any:
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if np.isnan(value) else float(value)
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, pd.Timestamp):
        return None if pd.isna(value) else value.strftime("%Y-%m-%d")
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    return str(value)


def as_num(df: pd.DataFrame, column: str) -> pd.Series:
    return pd.to_numeric(df[column], errors="coerce")


def clip_rate(series: pd.Series) -> pd.Series:
    return series.clip(lower=0.0, upper=1.0)


def safe_smoothed(num: pd.Series, den: pd.Series, prior: pd.Series, strength: pd.Series | float) -> pd.Series:
    strength_series = pd.Series(strength, index=num.index) if not isinstance(strength, pd.Series) else strength
    value = (num + strength_series * prior) / (den + strength_series)
    value = value.where((den >= 0) & (strength_series > 0) & prior.notna())
    return clip_rate(value)


def candidate_prior_source(denominator: pd.Series, current_source: pd.Series) -> pd.Series:
    source = current_source.fillna("").astype(str).str.strip().str.lower()
    out = pd.Series("prior_only", index=denominator.index, dtype=object)
    has_support = denominator.fillna(0.0) > 0.0
    out.loc[has_support & (source == "division")] = "division"
    out.loc[has_support & (source == "global")] = "global"
    return out


def support_scaled_strength(denominator: pd.Series, family: RateFamily) -> pd.Series:
    den = denominator.fillna(0.0).clip(lower=0.0)
    current = float(family.current_men_v2_strength)
    minimum = min(20.0, max(10.0, current / 3.0))
    scaled = current * (current / (den + current))
    return scaled.clip(lower=minimum, upper=current)


def estimate_strength_mom(
    sum_x: float,
    sum_n: float,
    sum_n2: float,
    sum_x2_over_n: float,
    count: int,
    fallback: float,
) -> float:
    """Beta-binomial prior strength via Kleinman weighted method of moments.

    Inputs are running sums over per-fighter (x = numerator, n = denominator)
    totals. Returns the estimated pseudo-count strength K = (1 - rho) / rho,
    clamped to [SEB_MIN_STRENGTH, SEB_MAX_STRENGTH]. Underdispersed data
    (rho <= 0, fighters indistinguishable) maps to maximum pooling; falls back
    to the family's fixed strength when the population is too small or the
    estimator is undefined.
    """
    if count < SEB_MIN_FIGHTERS or sum_n <= 0.0:
        return float(fallback)
    p_bar = sum_x / sum_n
    if not (0.0 < p_bar < 1.0):
        return float(fallback)
    between = sum_x2_over_n - (sum_x * sum_x) / sum_n
    m = float(count - 1)
    denom_term = sum_n - sum_n2 / sum_n - m
    if denom_term <= 0.0:
        return float(fallback)
    rho = (between / (p_bar * (1.0 - p_bar)) - m) / denom_term
    if not np.isfinite(rho):
        return float(fallback)
    if rho <= 0.0:
        return float(SEB_MAX_STRENGTH)
    if rho >= 1.0:
        return float(SEB_MIN_STRENGTH)
    strength = (1.0 - rho) / rho
    return float(min(max(strength, SEB_MIN_STRENGTH), SEB_MAX_STRENGTH))


def _family_population_records(df: pd.DataFrame, family: RateFamily) -> pd.DataFrame:
    """Long table of (event_date, fighter, x, n) prefight totals for one family.

    Built from the v2 advanced rows: per side, numerator is reconstructed as
    clip(rate, 0, 1) * denominator (the same reconstruction the candidate
    columns use). Rows are deduplicated per (event_date, fighter) and sorted
    deterministically so the running-sum estimation is identical wherever it
    is computed (training rebuild and live path).
    """
    frames: list[pd.DataFrame] = []
    for side in ["a", "b"]:
        columns = existing_side_columns(side, family)
        id_column = f"fighter_{side}_id"
        if id_column not in df.columns:
            id_column = f"fighter_{side}"
        if (
            id_column not in df.columns
            or columns["prefight_rate"] not in df.columns
            or columns["denominator"] not in df.columns
        ):
            continue
        frame = pd.DataFrame(
            {
                "event_date": pd.to_datetime(df["event_date"], errors="coerce"),
                "fighter": df[id_column].astype(str).str.strip(),
                "rate": clip_rate(as_num(df, columns["prefight_rate"])),
                "den": as_num(df, columns["denominator"]).clip(lower=0.0),
            }
        )
        frames.append(frame)
    if not frames:
        return pd.DataFrame(columns=["event_date", "fighter", "x", "n"])
    records = pd.concat(frames, ignore_index=True)
    records = records[
        records["event_date"].notna()
        & (records["fighter"] != "")
        & records["den"].notna()
        & (records["den"] > 0.0)
        & records["rate"].notna()
    ].copy()
    records["x"] = np.minimum(records["rate"] * records["den"], records["den"]).clip(lower=0.0)
    records["n"] = records["den"]
    records = records.sort_values(["event_date", "fighter"], kind="mergesort")
    records = records.drop_duplicates(["event_date", "fighter"], keep="first")
    return records[["event_date", "fighter", "x", "n"]].reset_index(drop=True)


def build_strength_lookup(df: pd.DataFrame) -> dict[str, dict[str, Any]]:
    """Per family: estimated strength as a step function over event dates.

    For each unique event date d, ``strength_before[i]`` is the strength
    estimated from the population of per-fighter latest prefight totals
    strictly before d, so rows at d never see same-day or future data.
    ``strength_final`` covers cutoffs after the last observed date.
    """
    lookup: dict[str, dict[str, Any]] = {}
    for family in RATE_FAMILIES:
        records = _family_population_records(df, family)
        fallback = float(family.current_men_v2_strength)
        if records.empty:
            lookup[family.family] = {
                "dates": np.array([], dtype="datetime64[ns]"),
                "strength_before": np.array([], dtype=float),
                "strength_final": fallback,
                "fallback": fallback,
            }
            continue
        fighter_totals: dict[str, tuple[float, float]] = {}
        sum_x = sum_n = sum_n2 = sum_x2_over_n = 0.0
        dates: list[Any] = []
        strengths: list[float] = []
        for event_date, group in records.groupby("event_date", sort=True):
            dates.append(event_date)
            strengths.append(
                estimate_strength_mom(sum_x, sum_n, sum_n2, sum_x2_over_n, len(fighter_totals), fallback)
            )
            for fighter, x, n in zip(group["fighter"], group["x"], group["n"]):
                previous = fighter_totals.get(fighter)
                if previous is not None:
                    old_x, old_n = previous
                    sum_x -= old_x
                    sum_n -= old_n
                    sum_n2 -= old_n * old_n
                    sum_x2_over_n -= (old_x * old_x) / old_n
                fighter_totals[fighter] = (float(x), float(n))
                sum_x += float(x)
                sum_n += float(n)
                sum_n2 += float(n) * float(n)
                sum_x2_over_n += (float(x) * float(x)) / float(n)
        lookup[family.family] = {
            "dates": np.array(dates, dtype="datetime64[ns]"),
            "strength_before": np.array(strengths, dtype=float),
            "strength_final": estimate_strength_mom(
                sum_x, sum_n, sum_n2, sum_x2_over_n, len(fighter_totals), fallback
            ),
            "fallback": fallback,
        }
    return lookup


def strength_at(lookup_entry: dict[str, Any], cutoff: Any) -> float:
    """Estimated strength using only records strictly before ``cutoff``."""
    parsed = pd.to_datetime(cutoff, errors="coerce")
    if pd.isna(parsed):
        return float(lookup_entry["fallback"])
    dates = lookup_entry["dates"]
    if len(dates) == 0:
        return float(lookup_entry["fallback"])
    index = int(np.searchsorted(dates, np.datetime64(parsed), side="left"))
    if index >= len(dates):
        return float(lookup_entry["strength_final"])
    return float(lookup_entry["strength_before"][index])


def strength_series_for_rows(lookup_entry: dict[str, Any], event_dates: pd.Series) -> pd.Series:
    parsed = pd.to_datetime(event_dates, errors="coerce")
    values = np.full(len(parsed), float(lookup_entry["fallback"]), dtype=float)
    dates = lookup_entry["dates"]
    valid = parsed.notna().to_numpy()
    if len(dates) > 0 and valid.any():
        indices = np.searchsorted(dates, parsed.to_numpy(dtype="datetime64[ns]")[valid], side="left")
        resolved = np.where(
            indices >= len(dates),
            float(lookup_entry["strength_final"]),
            lookup_entry["strength_before"][np.minimum(indices, len(dates) - 1)],
        )
        values[valid] = resolved
    return pd.Series(values, index=event_dates.index)


def side_col(side: str, family: RateFamily, suffix: str) -> str:
    return f"fighter_{side}_v3_bayes_{family.family}_{suffix}"


def diff_col(family: RateFamily, suffix: str) -> str:
    return f"v3_bayes_{family.family}_{suffix}"


def existing_side_columns(side: str, family: RateFamily) -> dict[str, str]:
    prefix = f"fighter_{side}_"
    return {
        "prefight_rate": f"{prefix}{family.prefight_rate_suffix}",
        "denominator": f"{prefix}{family.current_v2_base}_support_before",
        "prior_rate": f"{prefix}{family.current_v2_base}_prior_rate_before",
        "prior_source": f"{prefix}{family.current_v2_base}_prior_source_before",
        "prior_denominator": f"{prefix}{family.current_v2_base}_prior_den_before",
    }


def family_available(df: pd.DataFrame, family: RateFamily) -> tuple[bool, list[str]]:
    required: list[str] = []
    for side in ["a", "b"]:
        required.extend(existing_side_columns(side, family).values())
    missing = [column for column in required if column not in df.columns]
    return not missing, missing


def add_side_family_columns(
    out: pd.DataFrame,
    side: str,
    family: RateFamily,
    seb_strength: pd.Series,
) -> list[str]:
    columns = existing_side_columns(side, family)
    rate = clip_rate(as_num(out, columns["prefight_rate"]))
    den = as_num(out, columns["denominator"]).clip(lower=0.0)
    prior = clip_rate(as_num(out, columns["prior_rate"]).fillna(family.neutral_prior))
    prior_den = as_num(out, columns["prior_denominator"]).fillna(0.0).clip(lower=0.0)
    source = candidate_prior_source(den, out[columns["prior_source"]])
    numerator_estimate = (rate * den).where(den > 0.0, 0.0)
    numerator_estimate = numerator_estimate.clip(lower=0.0)
    numerator_estimate = np.minimum(numerator_estimate, den)
    numerator_estimate = pd.Series(numerator_estimate, index=out.index)
    scaled_strength = support_scaled_strength(den, family)

    created = [
        side_col(side, family, "prefight_rate_before"),
        side_col(side, family, "raw_num_estimate_before"),
        side_col(side, family, "denominator_before"),
        side_col(side, family, "prior_mean_used"),
        side_col(side, family, "global_prior_mean"),
        side_col(side, family, "division_prior_mean"),
        side_col(side, family, "prior_source"),
        side_col(side, family, "prior_denominator"),
        side_col(side, family, "s20_women_style"),
        side_col(side, family, "s50_moderate"),
        side_col(side, family, "current_men_v2_strength"),
        side_col(side, family, "support_scaled"),
        side_col(side, family, "support_scaled_strength"),
        side_col(side, family, "seb"),
        side_col(side, family, "seb_strength"),
        side_col(side, family, "prior_only_flag"),
        side_col(side, family, "low_support_flag"),
    ]

    out[created[0]] = rate
    out[created[1]] = numerator_estimate
    out[created[2]] = den
    out[created[3]] = prior
    out[created[4]] = prior.where(source == "global")
    out[created[5]] = prior.where(source == "division")
    out[created[6]] = source
    out[created[7]] = prior_den
    out[created[8]] = safe_smoothed(numerator_estimate, den, prior, 20.0)
    out[created[9]] = safe_smoothed(numerator_estimate, den, prior, 50.0)
    out[created[10]] = safe_smoothed(numerator_estimate, den, prior, family.current_men_v2_strength)
    out[created[11]] = safe_smoothed(numerator_estimate, den, prior, scaled_strength)
    out[created[12]] = scaled_strength
    out[created[13]] = safe_smoothed(numerator_estimate, den, prior, seb_strength)
    out[created[14]] = seb_strength
    out[created[15]] = (source == "prior_only").astype(int)
    out[created[16]] = (den < family.low_support_threshold).astype(int)
    return created


def add_diff_family_columns(out: pd.DataFrame, family: RateFamily) -> list[str]:
    created: list[str] = []
    for suffix in [
        "s20_women_style",
        "s50_moderate",
        "current_men_v2_strength",
        "support_scaled",
        "seb",
    ]:
        col = diff_col(family, f"{suffix}_diff")
        out[col] = as_num(out, side_col("a", family, suffix)) - as_num(out, side_col("b", family, suffix))
        created.append(col)

    a_den = as_num(out, side_col("a", family, "denominator_before"))
    b_den = as_num(out, side_col("b", family, "denominator_before"))
    a_low = as_num(out, side_col("a", family, "low_support_flag")).fillna(0).astype(int)
    b_low = as_num(out, side_col("b", family, "low_support_flag")).fillna(0).astype(int)
    a_prior_only = as_num(out, side_col("a", family, "prior_only_flag")).fillna(0).astype(int)
    b_prior_only = as_num(out, side_col("b", family, "prior_only_flag")).fillna(0).astype(int)

    out[diff_col(family, "support_diff")] = a_den - b_den
    out[diff_col(family, "support_min")] = pd.concat([a_den, b_den], axis=1).min(axis=1)
    out[diff_col(family, "support_asymmetry_abs")] = (a_den - b_den).abs()
    out[diff_col(family, "either_low_support_flag")] = ((a_low == 1) | (b_low == 1)).astype(int)
    out[diff_col(family, "both_low_support_flag")] = ((a_low == 1) & (b_low == 1)).astype(int)
    out[diff_col(family, "either_prior_only_flag")] = ((a_prior_only == 1) | (b_prior_only == 1)).astype(int)
    created.extend(
        [
            diff_col(family, "support_diff"),
            diff_col(family, "support_min"),
            diff_col(family, "support_asymmetry_abs"),
            diff_col(family, "either_low_support_flag"),
            diff_col(family, "both_low_support_flag"),
            diff_col(family, "either_prior_only_flag"),
        ]
    )
    return created


def add_candidate_features(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str], dict[str, Any]]:
    out = df.copy()
    created: list[str] = []
    family_audit: dict[str, Any] = {}
    strength_lookup = build_strength_lookup(df)
    for family in RATE_FAMILIES:
        available, missing = family_available(out, family)
        lookup_entry = strength_lookup[family.family]
        family_audit[family.family] = {
            "available": bool(available),
            "display_name": family.display_name,
            "current_v2_base": family.current_v2_base,
            "prefight_rate_suffix": family.prefight_rate_suffix,
            "exact_raw_numerator_column_available": False,
            "numerator_source": "estimated_from_prefight_rate_before_times_denominator_before",
            "denominator_source": "existing_v2_support_before_column",
            "neutral_prior": family.neutral_prior,
            "current_men_v2_strength": family.current_men_v2_strength,
            "division_prior_denominator_threshold": family.division_prior_denominator_threshold,
            "low_support_threshold": family.low_support_threshold,
            "missing_required_columns": missing,
            "seb_strength_final": float(lookup_entry["strength_final"]),
            "seb_strength_min": (
                float(np.min(lookup_entry["strength_before"]))
                if len(lookup_entry["strength_before"])
                else float(lookup_entry["fallback"])
            ),
            "seb_strength_max": (
                float(np.max(lookup_entry["strength_before"]))
                if len(lookup_entry["strength_before"])
                else float(lookup_entry["fallback"])
            ),
            "seb_clamp_range": [SEB_MIN_STRENGTH, SEB_MAX_STRENGTH],
            "seb_min_fighters": SEB_MIN_FIGHTERS,
        }
        if not available:
            continue
        seb_strength = strength_series_for_rows(lookup_entry, out["event_date"])
        for side in ["a", "b"]:
            created.extend(add_side_family_columns(out, side, family, seb_strength))
        created.extend(add_diff_family_columns(out, family))
    return out, created, family_audit


def paired_frames(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
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


def _text_equal(a: pd.Series, b: pd.Series) -> pd.Series:
    return a.fillna("").astype(str) == b.fillna("").astype(str)


def _num_equal(a: pd.Series, b: pd.Series) -> pd.Series:
    a_num = pd.to_numeric(a, errors="coerce")
    b_num = pd.to_numeric(b, errors="coerce")
    both_missing = a_num.isna() & b_num.isna()
    return both_missing | ((a_num - b_num).abs() <= 1e-8)


def mirror_audit(df: pd.DataFrame, available_families: list[RateFamily]) -> dict[str, Any]:
    canonical, mirror = paired_frames(df)
    audit: dict[str, Any] = {
        "fight_groups": int(df["fight_id"].nunique()) if "fight_id" in df.columns else 0,
        "two_row_fight_groups": 0,
        "non_two_row_fight_groups": 0,
        "signed_diff_violations": 0,
        "symmetric_violations": 0,
        "side_swap_violations": 0,
        "sample_violations": [],
    }
    if "fight_id" in df.columns:
        sizes = df.groupby("fight_id", dropna=False).size()
        audit["two_row_fight_groups"] = int((sizes == 2).sum())
        audit["non_two_row_fight_groups"] = int((sizes != 2).sum())
    if canonical.empty:
        audit["mirror_passed"] = False
        audit["sample_violations"].append({"reason": "missing canonical/mirror row_direction pairs"})
        return audit

    signed_columns = [
        diff_col(family, suffix)
        for family in available_families
        for suffix in [
            "s20_women_style_diff",
            "s50_moderate_diff",
            "current_men_v2_strength_diff",
            "support_scaled_diff",
            "seb_diff",
            "support_diff",
        ]
    ]
    symmetric_columns = [
        diff_col(family, suffix)
        for family in available_families
        for suffix in [
            "support_min",
            "support_asymmetry_abs",
            "either_low_support_flag",
            "both_low_support_flag",
            "either_prior_only_flag",
        ]
    ]
    side_suffixes = [
        "prefight_rate_before",
        "raw_num_estimate_before",
        "denominator_before",
        "prior_mean_used",
        "prior_source",
        "prior_denominator",
        "s20_women_style",
        "s50_moderate",
        "current_men_v2_strength",
        "support_scaled",
        "support_scaled_strength",
        "seb",
        "seb_strength",
        "prior_only_flag",
        "low_support_flag",
    ]

    for column in signed_columns:
        if column not in df.columns:
            continue
        a = pd.to_numeric(canonical[column], errors="coerce")
        b = pd.to_numeric(mirror[column], errors="coerce")
        both_missing = a.isna() & b.isna()
        mismatch = (~both_missing) & (a.isna() | b.isna() | ((a + b).abs() > 1e-8))
        audit["signed_diff_violations"] += int(mismatch.sum())
        for fight_id in canonical.loc[mismatch].index[:5]:
            audit["sample_violations"].append(
                {
                    "check": "signed_diff",
                    "fight_id": fight_id,
                    "column": column,
                    "canonical": json_default(a.loc[fight_id]),
                    "mirror": json_default(b.loc[fight_id]),
                }
            )

    for column in symmetric_columns:
        if column not in df.columns:
            continue
        if pd.api.types.is_numeric_dtype(canonical[column]) or pd.api.types.is_numeric_dtype(mirror[column]):
            equal = _num_equal(canonical[column], mirror[column])
        else:
            equal = _text_equal(canonical[column], mirror[column])
        mismatch = ~equal
        audit["symmetric_violations"] += int(mismatch.sum())
        for fight_id in canonical.loc[mismatch].index[:5]:
            audit["sample_violations"].append(
                {
                    "check": "symmetric",
                    "fight_id": fight_id,
                    "column": column,
                    "canonical": json_default(canonical.loc[fight_id, column]),
                    "mirror": json_default(mirror.loc[fight_id, column]),
                }
            )

    for family in available_families:
        for suffix in side_suffixes:
            a_col = side_col("a", family, suffix)
            b_col = side_col("b", family, suffix)
            if a_col not in df.columns or b_col not in df.columns:
                continue
            if pd.api.types.is_numeric_dtype(canonical[a_col]) or pd.api.types.is_numeric_dtype(mirror[b_col]):
                equal_forward = _num_equal(canonical[a_col], mirror[b_col])
                equal_reverse = _num_equal(canonical[b_col], mirror[a_col])
            else:
                equal_forward = _text_equal(canonical[a_col], mirror[b_col])
                equal_reverse = _text_equal(canonical[b_col], mirror[a_col])
            mismatch = ~(equal_forward & equal_reverse)
            audit["side_swap_violations"] += int(mismatch.sum())
            for fight_id in canonical.loc[mismatch].index[:5]:
                audit["sample_violations"].append(
                    {
                        "check": "side_swap",
                        "fight_id": fight_id,
                        "family": family.family,
                        "suffix": suffix,
                    }
                )

    audit["sample_violations"] = audit["sample_violations"][:20]
    audit["mirror_passed"] = (
        audit["non_two_row_fight_groups"] == 0
        and audit["signed_diff_violations"] == 0
        and audit["symmetric_violations"] == 0
        and audit["side_swap_violations"] == 0
    )
    return audit


def new_column_missingness(df: pd.DataFrame, columns: list[str]) -> dict[str, Any]:
    rows = max(len(df), 1)
    summary = []
    for column in columns:
        missing = int(df[column].isna().sum())
        numeric = pd.to_numeric(df[column], errors="coerce")
        is_numeric = bool(pd.api.types.is_numeric_dtype(df[column]) or numeric.notna().any())
        summary.append(
            {
                "column": column,
                "missing_count": missing,
                "missing_pct": missing / rows * 100.0,
                "is_numeric": is_numeric,
                "min": None if not is_numeric or numeric.dropna().empty else float(numeric.min()),
                "max": None if not is_numeric or numeric.dropna().empty else float(numeric.max()),
            }
        )
    top = sorted(summary, key=lambda item: item["missing_pct"], reverse=True)[:25]
    core_columns = [
        column
        for column in columns
        if any(
            column.endswith(suffix)
            for suffix in [
                "s20_women_style",
                "s50_moderate",
                "current_men_v2_strength",
                "support_scaled",
                "s20_women_style_diff",
                "s50_moderate_diff",
                "current_men_v2_strength_diff",
                "support_scaled_diff",
                "seb",
                "seb_diff",
                "denominator_before",
                "support_diff",
            ]
        )
    ]
    core_missing = {
        column: float(df[column].isna().mean() * 100.0)
        for column in core_columns
        if column in df.columns
    }
    return {
        "top_missing_new_columns": top,
        "core_column_max_missing_pct": max(core_missing.values()) if core_missing else 0.0,
        "nan_explosion_passed": bool(not core_missing or max(core_missing.values()) <= 1.0),
    }


def latest_date(df: pd.DataFrame) -> str | None:
    if "event_date" not in df.columns:
        return None
    parsed = pd.to_datetime(df["event_date"], errors="coerce")
    if parsed.dropna().empty:
        return None
    return parsed.max().strftime("%Y-%m-%d")


def build_manifest_rows(created_columns: list[str], available_families: list[RateFamily]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    family_by_key = {family.family: family for family in available_families}
    for column in created_columns:
        family_name = ""
        side_or_diff = "unknown"
        smoothing_strength = ""
        prior_source = ""
        notes = "candidate-only Bayesian smoothing diagnostic"
        for key, family in family_by_key.items():
            if f"_{key}_" in column:
                family_name = family.display_name
                break
        if column.startswith("fighter_a_"):
            side_or_diff = "fighter_a"
        elif column.startswith("fighter_b_"):
            side_or_diff = "fighter_b"
        elif column.endswith("_diff"):
            side_or_diff = "diff"
        else:
            side_or_diff = "matchup_support"

        if "s20_women_style" in column:
            smoothing_strength = "s20_women_style"
        elif "s50_moderate" in column:
            smoothing_strength = "s50_moderate"
        elif "current_men_v2_strength" in column:
            smoothing_strength = "current_men_v2"
        elif "support_scaled" in column:
            smoothing_strength = "support_scaled"
        elif "_seb" in column:
            smoothing_strength = "seb_empirical_bayes"
        elif "denominator" in column or "support" in column:
            smoothing_strength = "support"
        elif "prior" in column:
            smoothing_strength = "prior_context"

        if "global_prior_mean" in column:
            prior_source = "global"
        elif "division_prior_mean" in column:
            prior_source = "division"
        elif "prior_only" in column:
            prior_source = "prior_only"
        elif "prior_source" in column or "prior_mean_used" in column:
            prior_source = "global/division/prior_only"

        if "raw_num_estimate" in column:
            notes = "estimated from prefight raw rate and denominator; exact raw numerator column is unavailable"
        elif "denominator_before" in column:
            notes = "existing prefight support/denominator from men v2 smoothing surface"
        elif "low_support_flag" in column:
            notes = "diagnostic support flag, not used by default model"

        rows.append(
            {
                "column_name": column,
                "feature_family": family_name or "bayes_smoothing_support",
                "side_or_diff": side_or_diff,
                "smoothing_strength": smoothing_strength,
                "prior_source": prior_source,
                "prefight_safe": True,
                "live_computable": True,
                "used_by_default": False,
                "candidate_only": True,
                "notes": notes,
            }
        )
    return rows


def write_manifest(path: Path, created_columns: list[str], available_families: list[RateFamily]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(build_manifest_rows(created_columns, available_families)).to_csv(path, index=False)


def build_audit(
    source: pd.DataFrame,
    output: pd.DataFrame,
    created_columns: list[str],
    family_audit: dict[str, Any],
    manifest_path: str | None,
) -> dict[str, Any]:
    available_families = [family for family in RATE_FAMILIES if family_audit[family.family]["available"]]
    unavailable = [family.family for family in RATE_FAMILIES if not family_audit[family.family]["available"]]
    new_columns_with_postfight_tokens = [
        column
        for column in created_columns
        if any(token in column.lower() for token in TARGET_OR_POSTFIGHT_TOKENS)
    ]
    missingness = new_column_missingness(output, created_columns)
    mirror = mirror_audit(output, available_families)
    source_latest = latest_date(source)
    output_latest = latest_date(output)
    exact_numerators_available = all(
        bool(item["exact_raw_numerator_column_available"]) for item in family_audit.values()
    )
    exact_numerators_unavailable = [
        family for family, item in family_audit.items() if not item["exact_raw_numerator_column_available"]
    ]
    row_count_passed = len(source) == len(output)
    latest_passed = source_latest == output_latest
    safe_columns_passed = not new_columns_with_postfight_tokens
    audit = {
        "script_version": SCRIPT_VERSION,
        "status": "PASS",
        "candidate_default_status": False,
        "promotion_status": False,
        "defaults_changed": False,
        "input_rows": int(source.shape[0]),
        "output_rows": int(output.shape[0]),
        "input_columns": int(source.shape[1]),
        "output_columns": int(output.shape[1]),
        "new_columns_count": int(len(created_columns)),
        "new_columns": created_columns,
        "candidate_file_adds_columns_only": bool(set(source.columns).issubset(set(output.columns))),
        "available_rate_families": [family.family for family in available_families],
        "unavailable_rate_families": unavailable,
        "family_audit": family_audit,
        "exact_raw_numerator_columns_available": bool(exact_numerators_available),
        "exact_raw_numerator_columns_unavailable": exact_numerators_unavailable,
        "numerator_handling": (
            "Exact raw numerator-before columns are not present in the v2 advanced CSV; "
            "candidate numerator estimates are derived only from existing prefight rate "
            "and denominator/support columns and are labeled raw_num_estimate_before."
        ),
        "source_columns_used": sorted(
            {
                column
                for family in available_families
                for side in ["a", "b"]
                for column in existing_side_columns(side, family).values()
            }
        ),
        "row_count_check": {"passed": bool(row_count_passed)},
        "fight_id_groups_two_row_mirrored_check": mirror,
        "target_or_postfight_columns_added_check": {
            "passed": bool(safe_columns_passed),
            "flagged_new_columns": new_columns_with_postfight_tokens,
        },
        "prefight_safe_check": {
            "passed": bool(safe_columns_passed),
            "basis": "all generated columns use existing prefight rate, support, prior-rate, prior-source, and prior-denominator inputs",
        },
        "target_result_not_used_check": {
            "passed": True,
            "excluded_input_columns": [
                column
                for column in source.columns
                if any(token in column.lower() for token in TARGET_OR_POSTFIGHT_TOKENS)
            ],
        },
        "nan_explosion_check": missingness,
        "latest_date_check": {
            "passed": bool(latest_passed),
            "input_latest_date": source_latest,
            "output_latest_date": output_latest,
        },
        "candidate_default_status_check": {"passed": True, "candidate_default_status": False},
        "promotion_status_check": {"passed": True, "promotion_status": False},
        "manifest_path": manifest_path,
    }
    audit["all_safety_checks_passed"] = bool(
        row_count_passed
        and mirror.get("mirror_passed", False)
        and safe_columns_passed
        and missingness["nan_explosion_passed"]
        and latest_passed
        and audit["candidate_default_status_check"]["passed"]
        and audit["promotion_status_check"]["passed"]
    )
    if unavailable:
        audit["status"] = "PARTIAL"
    if not audit["all_safety_checks_passed"]:
        audit["status"] = "FAIL"
    return audit


def main() -> int:
    args = parse_args()
    input_path = Path(args.input)
    out_path = Path(args.out)
    audit_path = Path(args.audit_out)
    manifest_path = Path(args.manifest_out) if str(args.manifest_out).strip() else None
    if not input_path.exists():
        raise FileNotFoundError(input_path)

    source = pd.read_csv(input_path)
    output, created_columns, family_audit = add_candidate_features(source)
    available_families = [family for family in RATE_FAMILIES if family_audit[family.family]["available"]]

    out_path.parent.mkdir(parents=True, exist_ok=True)
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    output.to_csv(out_path, index=False)
    if manifest_path is not None:
        write_manifest(manifest_path, created_columns, available_families)

    audit = build_audit(
        source=source,
        output=output,
        created_columns=created_columns,
        family_audit=family_audit,
        manifest_path=str(manifest_path) if manifest_path else None,
    )
    audit_path.write_text(json.dumps(audit, indent=2, default=json_default) + "\n", encoding="utf-8")
    print(json.dumps(audit, indent=2, default=json_default))
    return 0 if audit["status"] in {"PASS", "PARTIAL"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
