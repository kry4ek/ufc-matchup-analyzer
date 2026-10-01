#!/usr/bin/env python
# -*- coding: utf-8 -*-
r"""
build_prefight_bayesian_smoothing_v1_REBUILT.py

Build time-safe prefight Bayesian-smoothed rate features for the UFC women's model.

This script is intentionally non-destructive. It reads:
  1) Advanced model training rows, usually:
       output_advanced_features\ufc_womens_model_training_rows_advanced.csv
  2) Fighter-fight stats with raw landed/attempted counts, usually:
       output_td_repaired\ufc_womens_fighter_fight_stats_td_control_repaired.csv

It writes a new training dataset with extra prefight smoothed features.

Key anti-leakage rule:
  For each fighter-fight row in the fighter-stats file, cumulative numerator/denominator
  values are shifted by one row within fighter before smoothing. Therefore the current
  fight's stats are not used to predict that same fight.

Default smoothing formula:
  smoothed_rate = (past_num + prior_strength * prior_mean_before_date)
                  / (past_den + prior_strength)

The prior_mean_before_date is computed from past rows only. If --group-col is supplied
and the group has enough past denominator mass, the group prior is used; otherwise the
script falls back to the past global prior, then to --neutral-prior if no historical data exists.
"""

from __future__ import annotations

import argparse
import json
import math
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

SCRIPT_VERSION = "build_prefight_bayesian_smoothing_v1_REBUILT_2026_06_12_seb"

# Empirical-Bayes estimated prior strength ("seb"): beta-binomial weighted
# method of moments over per-fighter prefight totals strictly before each
# event date. Mirrors the men's seb implementation; duplicated here so the
# women's project stays self-contained.
SEB_MIN_STRENGTH = 5.0
SEB_MAX_STRENGTH = 500.0
SEB_MIN_FIGHTERS = 30
SEB_SUFFIX = "seb"


# Conservative default: only core cumulative rates likely to be useful and relatively stable.
CORE_SMOOTHING_PAIRS = [
    {
        "feature_base": "career_sig_str_accuracy_before_bayes",
        "numerator_col": "sig_str_landed_repaired",
        "denominator_col": "sig_str_attempted_repaired",
        "description": "Fighter career significant-strike accuracy, prefight, Bayesian smoothed",
    },
    {
        "feature_base": "career_sig_str_allowed_accuracy_before_bayes",
        "numerator_col": "opponent_sig_str_landed_repaired",
        "denominator_col": "opponent_sig_str_attempted_repaired",
        "description": "Opponent significant-strike accuracy allowed by fighter, prefight, Bayesian smoothed",
    },
    {
        "feature_base": "career_total_str_accuracy_before_bayes",
        "numerator_col": "total_str_landed",
        "denominator_col": "total_str_attempted",
        "description": "Fighter career total-strike accuracy, prefight, Bayesian smoothed",
    },
    {
        "feature_base": "career_total_str_allowed_accuracy_before_bayes",
        "numerator_col": "opponent_total_str_landed",
        "denominator_col": "opponent_total_str_attempted",
        "description": "Opponent total-strike accuracy allowed by fighter, prefight, Bayesian smoothed",
    },
    {
        "feature_base": "career_td_accuracy_before_bayes",
        "numerator_col": "td_landed",
        "denominator_col": "td_attempted",
        "description": "Fighter career takedown accuracy, prefight, Bayesian smoothed",
    },
    {
        "feature_base": "career_td_allowed_accuracy_before_bayes",
        "numerator_col": "opponent_td_landed",
        "denominator_col": "opponent_td_attempted",
        "description": "Opponent takedown accuracy allowed by fighter, prefight, Bayesian smoothed",
    },
]


@dataclass
class Schema:
    training_fighter_a_col: Optional[str]
    training_fighter_b_col: Optional[str]
    training_date_col: Optional[str]
    training_division_col: Optional[str]
    stats_fighter_col: Optional[str]
    stats_date_col: Optional[str]
    stats_division_col: Optional[str]
    selected_pairs: List[Dict[str, str]]
    missing_pair_columns: List[str]


@dataclass
class BuildResult:
    script_version: str
    training_rows_in: int
    training_rows_out: int
    training_cols_in: int
    training_cols_out: int
    fighter_stats_rows: int
    prior_strength: float
    group_col: Optional[str]
    min_group_denominator: float
    selected_feature_count: int
    output_csv: str
    feature_audit_csv: str
    merge_audit_csv: str
    summary_txt: str


def _read_csv(path: str | Path) -> pd.DataFrame:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    return pd.read_csv(path, low_memory=False)


def _ensure_out_dir(path: str | Path) -> Path:
    out = Path(path)
    out.mkdir(parents=True, exist_ok=True)
    return out


def _first_existing(columns: Iterable[str], candidates: Sequence[str]) -> Optional[str]:
    cols = set(columns)
    for c in candidates:
        if c in cols:
            return c
    # case-insensitive fallback
    lower_map = {str(c).lower(): c for c in columns}
    for c in candidates:
        if c.lower() in lower_map:
            return lower_map[c.lower()]
    return None


def detect_schema(training: pd.DataFrame, stats: pd.DataFrame, group_col: Optional[str] = None) -> Schema:
    training_fighter_a_col = _first_existing(
        training.columns,
        ["fighter_a", "red_fighter", "fighter_1", "fighter_a_name", "fighter"],
    )
    training_fighter_b_col = _first_existing(
        training.columns,
        ["fighter_b", "blue_fighter", "fighter_2", "fighter_b_name", "opponent"],
    )
    training_date_col = _first_existing(
        training.columns,
        ["event_date", "date", "fight_date", "event_dt"],
    )
    training_division_col = _first_existing(training.columns, ["division", "weight_class"])

    stats_fighter_col = _first_existing(
        stats.columns,
        ["fighter", "fighter_name", "name", "athlete", "competitor", "fighter_a"],
    )
    stats_date_col = _first_existing(stats.columns, ["event_date", "date", "fight_date", "event_dt"])
    stats_division_col = group_col if group_col and group_col in stats.columns else _first_existing(stats.columns, ["division", "weight_class"])

    missing_pair_columns: List[str] = []
    selected_pairs: List[Dict[str, str]] = []
    for pair in CORE_SMOOTHING_PAIRS:
        num = pair["numerator_col"]
        den = pair["denominator_col"]
        if num in stats.columns and den in stats.columns:
            selected_pairs.append(dict(pair))
        else:
            if num not in stats.columns:
                missing_pair_columns.append(num)
            if den not in stats.columns:
                missing_pair_columns.append(den)

    return Schema(
        training_fighter_a_col=training_fighter_a_col,
        training_fighter_b_col=training_fighter_b_col,
        training_date_col=training_date_col,
        training_division_col=training_division_col,
        stats_fighter_col=stats_fighter_col,
        stats_date_col=stats_date_col,
        stats_division_col=stats_division_col,
        selected_pairs=selected_pairs,
        missing_pair_columns=sorted(set(missing_pair_columns)),
    )


def _validate_schema(schema: Schema) -> None:
    missing = []
    if not schema.training_fighter_a_col:
        missing.append("training fighter_a column")
    if not schema.training_fighter_b_col:
        missing.append("training fighter_b column")
    if not schema.training_date_col:
        missing.append("training date column")
    if not schema.stats_fighter_col:
        missing.append("fighter-stats fighter column")
    if not schema.stats_date_col:
        missing.append("fighter-stats date column")
    if not schema.selected_pairs:
        missing.append("at least one selected numerator/denominator pair")
    if missing:
        raise ValueError("Could not detect required schema component(s): " + ", ".join(missing))


def _normalize_name_series(s: pd.Series) -> pd.Series:
    return s.astype(str).str.strip()


def _safe_numeric(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s, errors="coerce")


def _feature_suffix(prior_strength: float) -> str:
    # e.g., 20 -> s20, 7.5 -> s7p5
    if float(prior_strength).is_integer():
        val = str(int(prior_strength))
    else:
        val = str(prior_strength).replace(".", "p")
    return f"s{val}"


def _estimate_seb_strength_mom(
    sum_x: float,
    sum_n: float,
    sum_n2: float,
    sum_x2_over_n: float,
    count: int,
    fallback: float,
) -> float:
    """Beta-binomial prior strength via Kleinman weighted method of moments."""
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


def _estimate_seb_strength_series(
    s: pd.DataFrame,
    num_before_col: str,
    den_before_col: str,
    fallback: float,
) -> pd.Series:
    """Per-row estimated strength using only fighters' prefight totals strictly before each row's date.

    For each event date d, the population is every fighter's latest prefight
    (numerator, denominator) totals from rows dated strictly before d, so the
    estimate is leakage-free under the same standard as the smoothing itself.
    """
    records = pd.DataFrame(
        {
            "date": s["__event_date_key"],
            "fighter": s["__fighter_key"],
            "x": pd.to_numeric(s[num_before_col], errors="coerce"),
            "n": pd.to_numeric(s[den_before_col], errors="coerce"),
        },
        index=s.index,
    )
    records = records[
        records["date"].notna()
        & records["fighter"].notna()
        & records["n"].notna()
        & (records["n"] > 0.0)
        & records["x"].notna()
    ]
    records = records.sort_values(["date", "fighter"], kind="mergesort")
    records = records.drop_duplicates(["date", "fighter"], keep="first")

    fighter_totals: dict[str, tuple[float, float]] = {}
    sum_x = sum_n = sum_n2 = sum_x2_over_n = 0.0
    strength_by_date: dict[pd.Timestamp, float] = {}
    for date, group in records.groupby("date", sort=True):
        strength_by_date[date] = _estimate_seb_strength_mom(
            sum_x, sum_n, sum_n2, sum_x2_over_n, len(fighter_totals), fallback
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

    final_strength = _estimate_seb_strength_mom(
        sum_x, sum_n, sum_n2, sum_x2_over_n, len(fighter_totals), fallback
    )
    if strength_by_date:
        known_dates = pd.DatetimeIndex(sorted(strength_by_date))
        known_values = np.array([strength_by_date[d] for d in known_dates], dtype=float)

        def lookup(date: Any) -> float:
            if pd.isna(date):
                return float(fallback)
            index = int(known_dates.searchsorted(date, side="left"))
            if index >= len(known_dates):
                return float(final_strength)
            if known_dates[index] == date:
                return float(known_values[index])
            return float(known_values[index])

        return s["__event_date_key"].map(lookup).astype(float)
    return pd.Series(float(fallback), index=s.index)


def _prepare_stats_base(stats: pd.DataFrame, schema: Schema) -> pd.DataFrame:
    s = stats.copy()
    assert schema.stats_fighter_col is not None
    assert schema.stats_date_col is not None
    s["__fighter_key"] = _normalize_name_series(s[schema.stats_fighter_col])
    s["__event_date_key"] = pd.to_datetime(s[schema.stats_date_col], errors="coerce")

    # Stable tie-breakers if available. Same-date same-fighter duplicates should be rare.
    sort_cols = ["__fighter_key", "__event_date_key"]
    for c in ["event_name", "fight_id", "bout_id", "opponent", "result"]:
        if c in s.columns:
            sort_cols.append(c)
    s = s.sort_values(sort_cols, kind="mergesort").reset_index(drop=True)
    return s


def _compute_prior_means_before(
    s: pd.DataFrame,
    numerator: pd.Series,
    denominator: pd.Series,
    date_col: str,
    group_col: Optional[str],
    min_group_denominator: float,
    neutral_prior: float,
) -> Tuple[pd.Series, pd.Series, pd.Series]:
    """Return chosen_prior_mean, global_prior_before, group_prior_before.

    All priors are computed from rows strictly before the current event date by aggregating by event date.
    This avoids future leakage and avoids using same-card rows in the prior for each other.
    """
    df = pd.DataFrame(
        {
            "__date": s[date_col],
            "__num": numerator.fillna(0.0),
            "__den": denominator.fillna(0.0),
        },
        index=s.index,
    )

    # Global historical prior by date, shifted by one date.
    by_date = df.groupby("__date", dropna=False)[["__num", "__den"]].sum().sort_index()
    by_date["__cum_num_before"] = by_date["__num"].cumsum().shift(1).fillna(0.0)
    by_date["__cum_den_before"] = by_date["__den"].cumsum().shift(1).fillna(0.0)
    by_date["__global_prior_before"] = np.where(
        by_date["__cum_den_before"] > 0,
        by_date["__cum_num_before"] / by_date["__cum_den_before"],
        neutral_prior,
    )
    global_prior_before = df["__date"].map(by_date["__global_prior_before"])

    if group_col is None or group_col not in s.columns:
        group_prior_before = pd.Series(np.nan, index=s.index, dtype=float)
        chosen = global_prior_before.fillna(neutral_prior).clip(0.0, 1.0)
        return chosen, global_prior_before, group_prior_before

    g = s[group_col].astype(str).fillna("__MISSING_GROUP__")
    gd = pd.DataFrame(
        {
            "__group": g,
            "__date": s[date_col],
            "__num": numerator.fillna(0.0),
            "__den": denominator.fillna(0.0),
        },
        index=s.index,
    )
    by_group_date = (
        gd.groupby(["__group", "__date"], dropna=False)[["__num", "__den"]]
        .sum()
        .sort_index()
    )
    by_group_date["__cum_num_before"] = by_group_date.groupby(level=0)["__num"].cumsum().groupby(level=0).shift(1).fillna(0.0)
    by_group_date["__cum_den_before"] = by_group_date.groupby(level=0)["__den"].cumsum().groupby(level=0).shift(1).fillna(0.0)
    by_group_date["__group_prior_before"] = np.where(
        by_group_date["__cum_den_before"] > 0,
        by_group_date["__cum_num_before"] / by_group_date["__cum_den_before"],
        np.nan,
    )

    # Merge back by group/date, preserving original order.
    temp = gd[["__group", "__date"]].reset_index(names="__orig_index")
    pri = by_group_date[["__cum_den_before", "__group_prior_before"]].reset_index()
    temp = temp.merge(pri, on=["__group", "__date"], how="left")
    temp = temp.set_index("__orig_index").reindex(s.index)

    group_prior_before = temp["__group_prior_before"]
    group_den_before = temp["__cum_den_before"].fillna(0.0)

    chosen = np.where(
        group_den_before >= float(min_group_denominator),
        group_prior_before,
        global_prior_before,
    )
    chosen = pd.Series(chosen, index=s.index, dtype=float).fillna(neutral_prior).clip(0.0, 1.0)
    return chosen, global_prior_before, group_prior_before


def build_prefight_feature_table(
    stats: pd.DataFrame,
    schema: Schema,
    prior_strength: float,
    min_group_denominator: float,
    neutral_prior: float,
    add_seb: bool = False,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Return fighter/date prefight feature table and feature audit."""
    _validate_schema(schema)
    assert schema.stats_fighter_col is not None
    assert schema.stats_date_col is not None

    s = _prepare_stats_base(stats, schema)
    suffix = _feature_suffix(prior_strength)
    feature_audit_rows = []

    # One row per fighter-fight. We keep source keys for merging into training rows.
    feature_cols = ["__fighter_key", "__event_date_key"]
    if schema.stats_division_col and schema.stats_division_col in s.columns:
        feature_cols.append(schema.stats_division_col)

    for pair in schema.selected_pairs:
        num_col = pair["numerator_col"]
        den_col = pair["denominator_col"]
        base = pair["feature_base"]
        out_col = f"{base}_{suffix}"
        den_before_col = f"{base}_{suffix}_den_before"
        num_before_col = f"{base}_{suffix}_num_before"
        prior_col = f"{base}_{suffix}_prior_mean_before"

        num = _safe_numeric(s[num_col]).clip(lower=0)
        den = _safe_numeric(s[den_col]).clip(lower=0)

        # Basic validity: numerator cannot exceed denominator for landed/attempted style rates.
        invalid = (num.notna() & den.notna()) & ((den < 0) | (num < 0) | (num > den))
        den_nonpos = den.fillna(0) <= 0

        # For cumulative fighter history, set invalid current-fight rows to NaN then fill as 0 contribution.
        num_clean = num.mask(invalid)
        den_clean = den.mask(invalid)
        num_for_cumsum = num_clean.fillna(0.0)
        den_for_cumsum = den_clean.fillna(0.0)

        # Cumulative by fighter before current row: shift within fighter.
        s[num_before_col] = (
            num_for_cumsum.groupby(s["__fighter_key"]).cumsum().groupby(s["__fighter_key"]).shift(1).fillna(0.0)
        )
        s[den_before_col] = (
            den_for_cumsum.groupby(s["__fighter_key"]).cumsum().groupby(s["__fighter_key"]).shift(1).fillna(0.0)
        )

        group_col = schema.stats_division_col if schema.stats_division_col in s.columns else None
        chosen_prior, global_prior, group_prior = _compute_prior_means_before(
            s=s,
            numerator=num_clean,
            denominator=den_clean,
            date_col="__event_date_key",
            group_col=group_col,
            min_group_denominator=min_group_denominator,
            neutral_prior=neutral_prior,
        )
        s[prior_col] = chosen_prior
        s[out_col] = (s[num_before_col] + float(prior_strength) * s[prior_col]) / (
            s[den_before_col] + float(prior_strength)
        )
        s[out_col] = s[out_col].clip(0.0, 1.0)

        feature_cols.extend([out_col, den_before_col, num_before_col, prior_col])

        seb_audit: dict = {}
        if add_seb:
            seb_out_col = f"{base}_{SEB_SUFFIX}"
            seb_den_col = f"{base}_{SEB_SUFFIX}_den_before"
            seb_strength_col = f"{base}_{SEB_SUFFIX}_strength_used"
            seb_strength = _estimate_seb_strength_series(
                s,
                num_before_col=num_before_col,
                den_before_col=den_before_col,
                fallback=float(prior_strength),
            )
            s[seb_out_col] = (
                (s[num_before_col] + seb_strength * s[prior_col]) / (s[den_before_col] + seb_strength)
            ).clip(0.0, 1.0)
            s[seb_den_col] = s[den_before_col]
            s[seb_strength_col] = seb_strength
            feature_cols.extend([seb_out_col, seb_den_col, seb_strength_col])
            seb_audit = {
                "seb_strength_mean": float(seb_strength.mean()),
                "seb_strength_min": float(seb_strength.min()),
                "seb_strength_max": float(seb_strength.max()),
                "seb_strength_latest": float(seb_strength.iloc[-1]) if len(seb_strength) else float("nan"),
                "seb_clamp_range": f"[{SEB_MIN_STRENGTH}, {SEB_MAX_STRENGTH}]",
                "seb_min_fighters": SEB_MIN_FIGHTERS,
            }

        valid_current_rows = int((~invalid & num.notna() & den.notna() & (den > 0)).sum())
        rows_with_history = int((s[den_before_col] > 0).sum())
        feature_audit_rows.append(
            {
                "feature": out_col,
                "numerator_col": num_col,
                "denominator_col": den_col,
                "description": pair.get("description", ""),
                "current_rows_valid_den_gt_zero": valid_current_rows,
                "current_rows_invalid_num_gt_den_or_negative": int(invalid.sum()),
                "current_rows_den_zero_or_missing": int(den_nonpos.sum()),
                "rows_with_prefight_history_den_gt_zero": rows_with_history,
                "prefight_den_before_mean": float(s[den_before_col].mean()),
                "prefight_den_before_median": float(s[den_before_col].median()),
                "smoothed_mean": float(s[out_col].mean()),
                "smoothed_min": float(s[out_col].min()),
                "smoothed_max": float(s[out_col].max()),
                "prior_mean_before_mean": float(s[prior_col].mean()),
                "prior_strength": float(prior_strength),
                "group_col_used_for_prior": group_col or "",
                "min_group_denominator": float(min_group_denominator),
                **seb_audit,
            }
        )

    feature_table = s[feature_cols].copy()

    # Duplicates on fighter/date can make the training merge many-to-many. Collapse if needed.
    # For numeric prefight features, first is safe if duplicates are identical; otherwise mean is conservative.
    key_cols = ["__fighter_key", "__event_date_key"]
    dup_count = int(feature_table.duplicated(key_cols, keep=False).sum())
    if dup_count > 0:
        numeric_cols = [c for c in feature_table.columns if c not in key_cols and pd.api.types.is_numeric_dtype(feature_table[c])]
        non_numeric_cols = [c for c in feature_table.columns if c not in key_cols and c not in numeric_cols]
        agg = {c: "mean" for c in numeric_cols}
        agg.update({c: "first" for c in non_numeric_cols})
        feature_table = feature_table.groupby(key_cols, as_index=False, dropna=False).agg(agg)

    audit = pd.DataFrame(feature_audit_rows)
    audit.attrs["duplicate_fighter_date_rows_before_collapse"] = dup_count
    return feature_table, audit


def merge_features_into_training(
    training: pd.DataFrame,
    feature_table: pd.DataFrame,
    schema: Schema,
    prior_strength: float,
    add_seb: bool = False,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    _validate_schema(schema)
    assert schema.training_fighter_a_col is not None
    assert schema.training_fighter_b_col is not None
    assert schema.training_date_col is not None

    out = training.copy()
    original_index_name = "__training_row_id"
    out[original_index_name] = np.arange(len(out))
    out["__event_date_key"] = pd.to_datetime(out[schema.training_date_col], errors="coerce")
    out["__fighter_a_key"] = _normalize_name_series(out[schema.training_fighter_a_col])
    out["__fighter_b_key"] = _normalize_name_series(out[schema.training_fighter_b_col])

    suffixes = [_feature_suffix(prior_strength)] + ([SEB_SUFFIX] if add_seb else [])
    base_smoothed_cols = [
        c for c in feature_table.columns if any(c.endswith(f"_{sfx}") for sfx in suffixes)
    ]
    # Keep corresponding denominator columns too.
    helper_cols = [
        c for c in feature_table.columns if any(c.endswith(f"_{sfx}_den_before") for sfx in suffixes)
    ]
    merge_value_cols = base_smoothed_cols + helper_cols

    a_features = feature_table[["__fighter_key", "__event_date_key"] + merge_value_cols].copy()
    a_rename = {c: f"fighter_a_{c}" for c in merge_value_cols}
    a_features = a_features.rename(columns={"__fighter_key": "__fighter_a_key", **a_rename})

    b_features = feature_table[["__fighter_key", "__event_date_key"] + merge_value_cols].copy()
    b_rename = {c: f"fighter_b_{c}" for c in merge_value_cols}
    b_features = b_features.rename(columns={"__fighter_key": "__fighter_b_key", **b_rename})

    before_rows = len(out)
    out = out.merge(a_features, on=["__fighter_a_key", "__event_date_key"], how="left", validate="many_to_one")
    after_a_rows = len(out)
    out = out.merge(b_features, on=["__fighter_b_key", "__event_date_key"], how="left", validate="many_to_one")
    after_b_rows = len(out)

    # Diff columns: fighter A minus fighter B for smoothed values and denominators.
    created_diff_cols = []
    for c in base_smoothed_cols:
        a_col = f"fighter_a_{c}"
        b_col = f"fighter_b_{c}"
        # Remove career_ prefix from the diff if present, keep clear name.
        diff_base = c
        diff_col = f"{diff_base}_diff"
        out[diff_col] = out[a_col] - out[b_col]
        created_diff_cols.append(diff_col)

    merge_audit_rows = []
    for side, key_col, prefix in [
        ("fighter_a", "__fighter_a_key", "fighter_a_"),
        ("fighter_b", "__fighter_b_key", "fighter_b_"),
    ]:
        side_smoothed_cols = [f"{prefix}{c}" for c in base_smoothed_cols]
        any_missing = out[side_smoothed_cols].isna().all(axis=1) if side_smoothed_cols else pd.Series(True, index=out.index)
        merge_audit_rows.append(
            {
                "side": side,
                "rows": len(out),
                "rows_with_all_smoothed_features_missing": int(any_missing.sum()),
                "match_rate_any_smoothed_feature": float(1.0 - any_missing.mean()) if len(out) else np.nan,
                "unique_training_names": int(out[key_col].nunique(dropna=True)),
            }
        )
        for c in side_smoothed_cols:
            merge_audit_rows.append(
                {
                    "side": side,
                    "feature": c,
                    "rows": len(out),
                    "missing_rows": int(out[c].isna().sum()),
                    "missing_rate": float(out[c].isna().mean()) if len(out) else np.nan,
                    "mean": float(out[c].mean()) if out[c].notna().any() else np.nan,
                    "min": float(out[c].min()) if out[c].notna().any() else np.nan,
                    "max": float(out[c].max()) if out[c].notna().any() else np.nan,
                }
            )

    # Remove internal helper keys but preserve row ordering.
    out = out.sort_values(original_index_name, kind="mergesort").reset_index(drop=True)
    internal_cols = [original_index_name, "__event_date_key", "__fighter_a_key", "__fighter_b_key"]
    out = out.drop(columns=[c for c in internal_cols if c in out.columns])

    merge_audit = pd.DataFrame(merge_audit_rows)
    merge_audit.attrs["before_rows"] = before_rows
    merge_audit.attrs["after_a_rows"] = after_a_rows
    merge_audit.attrs["after_b_rows"] = after_b_rows
    merge_audit.attrs["created_diff_cols"] = created_diff_cols
    return out, merge_audit


def write_json(path: Path, obj: dict) -> None:
    def convert(x):
        if isinstance(x, (np.integer,)):
            return int(x)
        if isinstance(x, (np.floating,)):
            return float(x)
        if isinstance(x, (np.ndarray,)):
            return x.tolist()
        if isinstance(x, Path):
            return str(x)
        return x

    with path.open("w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, default=convert)


def command_inspect(args: argparse.Namespace) -> None:
    out_dir = _ensure_out_dir(args.out_dir)
    training = _read_csv(args.training_rows)
    stats = _read_csv(args.fighter_stats)
    schema = detect_schema(training, stats, group_col=args.group_col)

    print(f"Script version: {SCRIPT_VERSION}")
    print(f"Training rows: {args.training_rows}")
    print(f"Fighter stats:  {args.fighter_stats}")
    print(f"Training shape: {training.shape[0]:,} rows x {training.shape[1]:,} cols")
    print(f"Stats shape:    {stats.shape[0]:,} rows x {stats.shape[1]:,} cols")
    print("\nDetected training schema:")
    print(f"  fighter_a_col: {schema.training_fighter_a_col}")
    print(f"  fighter_b_col: {schema.training_fighter_b_col}")
    print(f"  date_col:      {schema.training_date_col}")
    print(f"  division_col:  {schema.training_division_col}")
    print("\nDetected fighter-stats schema:")
    print(f"  fighter_col:   {schema.stats_fighter_col}")
    print(f"  date_col:      {schema.stats_date_col}")
    print(f"  division_col:  {schema.stats_division_col}")
    print("\nSelected smoothing pairs:")
    if schema.selected_pairs:
        for p in schema.selected_pairs:
            print(f"  - {p['feature_base']}: {p['numerator_col']} / {p['denominator_col']}")
    else:
        print("  None detected.")
    if schema.missing_pair_columns:
        print("\nMissing expected raw columns:")
        for c in schema.missing_pair_columns:
            print(f"  - {c}")

    # Save useful schema/audit files.
    selected_df = pd.DataFrame(schema.selected_pairs)
    selected_path = out_dir / "prefight_bayesian_smoothing_selected_pairs.csv"
    selected_df.to_csv(selected_path, index=False)

    schema_path = out_dir / "prefight_bayesian_smoothing_inspect_manifest.json"
    write_json(
        schema_path,
        {
            "script_version": SCRIPT_VERSION,
            "training_rows": str(args.training_rows),
            "fighter_stats": str(args.fighter_stats),
            "training_shape": list(training.shape),
            "stats_shape": list(stats.shape),
            "schema": asdict(schema),
            "selected_pairs_csv": str(selected_path),
        },
    )
    print(f"\nSaved selected-pairs audit: {selected_path}")
    print(f"Saved inspect manifest:     {schema_path}")

    try:
        _validate_schema(schema)
        print("\nSchema status: OK. You can run the build command.")
    except Exception as exc:
        print(f"\nSchema status: NOT OK. {exc}")


def command_build(args: argparse.Namespace) -> None:
    out_dir = _ensure_out_dir(args.out_dir)
    training = _read_csv(args.training_rows)
    stats = _read_csv(args.fighter_stats)
    schema = detect_schema(training, stats, group_col=args.group_col)
    _validate_schema(schema)

    output_csv = out_dir / "ufc_womens_model_training_rows_advanced_plus_bayes_prefight_smoothing_v1.csv"
    feature_audit_csv = out_dir / "prefight_bayesian_smoothing_feature_audit.csv"
    merge_audit_csv = out_dir / "prefight_bayesian_smoothing_merge_audit.csv"
    summary_txt = out_dir / "prefight_bayesian_smoothing_summary.txt"
    manifest_json = out_dir / "prefight_bayesian_smoothing_manifest.json"

    print(f"Script version: {SCRIPT_VERSION}")
    print(f"Training rows: {args.training_rows}")
    print(f"Fighter stats:  {args.fighter_stats}")
    print(f"Prior strength: {args.prior_strength}")
    print(f"Group col requested: {args.group_col}")
    print(f"Min group denominator: {args.min_group_denominator}")
    print(f"Neutral prior fallback: {args.neutral_prior}")
    print("\nSelected smoothing pairs:")
    for p in schema.selected_pairs:
        print(f"  - {p['feature_base']}: {p['numerator_col']} / {p['denominator_col']}")

    feature_table, feature_audit = build_prefight_feature_table(
        stats=stats,
        schema=schema,
        prior_strength=args.prior_strength,
        min_group_denominator=args.min_group_denominator,
        neutral_prior=args.neutral_prior,
        add_seb=bool(getattr(args, "add_seb", False)),
    )
    print(f"\nBuilt prefight feature table: {feature_table.shape[0]:,} rows x {feature_table.shape[1]:,} cols")

    out_df, merge_audit = merge_features_into_training(
        training=training,
        feature_table=feature_table,
        schema=schema,
        prior_strength=args.prior_strength,
        add_seb=bool(getattr(args, "add_seb", False)),
    )

    out_df.to_csv(output_csv, index=False)
    feature_audit.to_csv(feature_audit_csv, index=False)
    merge_audit.to_csv(merge_audit_csv, index=False)

    added_cols = [c for c in out_df.columns if c not in training.columns]
    smoothed_added = [c for c in added_cols if c.endswith(f"_{_feature_suffix(args.prior_strength)}")]
    diff_added = [c for c in added_cols if c.endswith("_diff") and "bayes" in c]
    denominator_added = [c for c in added_cols if c.endswith(f"_{_feature_suffix(args.prior_strength)}_den_before")]

    result = BuildResult(
        script_version=SCRIPT_VERSION,
        training_rows_in=len(training),
        training_rows_out=len(out_df),
        training_cols_in=training.shape[1],
        training_cols_out=out_df.shape[1],
        fighter_stats_rows=len(stats),
        prior_strength=float(args.prior_strength),
        group_col=schema.stats_division_col if schema.stats_division_col else None,
        min_group_denominator=float(args.min_group_denominator),
        selected_feature_count=len(schema.selected_pairs),
        output_csv=str(output_csv),
        feature_audit_csv=str(feature_audit_csv),
        merge_audit_csv=str(merge_audit_csv),
        summary_txt=str(summary_txt),
    )

    write_json(
        manifest_json,
        {
            "result": asdict(result),
            "schema": asdict(schema),
            "added_columns_count": len(added_cols),
            "added_columns": added_cols,
            "smoothed_columns_added": smoothed_added,
            "diff_columns_added": diff_added,
            "denominator_columns_added": denominator_added,
            "feature_table_rows": int(feature_table.shape[0]),
            "feature_table_cols": int(feature_table.shape[1]),
            "duplicate_fighter_date_rows_before_collapse": int(feature_audit.attrs.get("duplicate_fighter_date_rows_before_collapse", 0)),
            "merge_row_counts": {
                "before_rows": int(merge_audit.attrs.get("before_rows", len(training))),
                "after_a_rows": int(merge_audit.attrs.get("after_a_rows", len(training))),
                "after_b_rows": int(merge_audit.attrs.get("after_b_rows", len(training))),
            },
            "created_diff_cols": merge_audit.attrs.get("created_diff_cols", []),
        },
    )

    lines = []
    lines.append(f"Script version: {SCRIPT_VERSION}")
    lines.append(f"Training input: {args.training_rows}")
    lines.append(f"Fighter-stats input: {args.fighter_stats}")
    lines.append(f"Training rows in/out: {len(training):,} -> {len(out_df):,}")
    lines.append(f"Training cols in/out: {training.shape[1]:,} -> {out_df.shape[1]:,}")
    lines.append(f"Added columns: {len(added_cols):,}")
    lines.append(f"Added smoothed A/B value columns: {len(smoothed_added):,}")
    lines.append(f"Added smoothed diff columns: {len(diff_added):,}")
    lines.append(f"Added denominator-before reliability columns: {len(denominator_added):,}")
    lines.append(f"Prior strength: {args.prior_strength}")
    lines.append(f"Group prior column used: {schema.stats_division_col}")
    lines.append(f"Min group denominator: {args.min_group_denominator}")
    lines.append(f"Neutral prior fallback: {args.neutral_prior}")
    lines.append("")
    lines.append("Selected smoothing pairs:")
    for p in schema.selected_pairs:
        lines.append(f"  - {p['feature_base']}: {p['numerator_col']} / {p['denominator_col']}")
    lines.append("")
    lines.append("Output files:")
    lines.append(f"  - {output_csv}")
    lines.append(f"  - {feature_audit_csv}")
    lines.append(f"  - {merge_audit_csv}")
    lines.append(f"  - {manifest_json}")
    summary_txt.write_text("\n".join(lines), encoding="utf-8")

    print("\nBuild complete.")
    print(f"Output dataset: {output_csv}")
    print(f"Feature audit:  {feature_audit_csv}")
    print(f"Merge audit:    {merge_audit_csv}")
    print(f"Summary:        {summary_txt}")
    print(f"Manifest:       {manifest_json}")
    print(f"Rows preserved: {'YES' if len(training) == len(out_df) else 'NO'} ({len(training):,} -> {len(out_df):,})")
    print(f"Added columns:  {len(added_cols):,}")

    if len(training) != len(out_df):
        raise RuntimeError("Row count changed during merge. Do not use output until investigated.")


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build time-safe prefight Bayesian-smoothed rate features for UFC women's model datasets."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--training-rows", required=True, help="Advanced training rows CSV.")
    common.add_argument("--fighter-stats", required=True, help="Fighter-fight stats CSV with raw landed/attempted counts.")
    common.add_argument("--out-dir", required=True, help="Output directory.")
    common.add_argument("--group-col", default="division", help="Optional group column for group-specific priors. Default: division.")

    p_inspect = sub.add_parser("inspect", parents=[common], help="Inspect schemas and selected smoothing pairs.")
    p_inspect.set_defaults(func=command_inspect)

    p_build = sub.add_parser("build", parents=[common], help="Build new training dataset with prefight Bayesian smoothing features.")
    p_build.add_argument("--prior-strength", type=float, default=20.0, help="Pseudo-denominator strength for the prior. Default: 20.")
    p_build.add_argument(
        "--add-seb",
        action="store_true",
        help=(
            "Also emit empirical-Bayes estimated-strength columns (suffix _seb): per smoothing "
            "pair the prior strength is estimated by beta-binomial method of moments from "
            "fighters' prefight totals strictly before each event date."
        ),
    )
    p_build.add_argument(
        "--min-group-denominator",
        type=float,
        default=200.0,
        help="Minimum past group denominator before using group prior instead of global prior. Default: 200.",
    )
    p_build.add_argument(
        "--neutral-prior",
        type=float,
        default=0.5,
        help="Fallback prior mean when no past data exists. Default: 0.5.",
    )
    p_build.set_defaults(func=command_build)

    return parser


def main(argv: Optional[Sequence[str]] = None) -> None:
    parser = make_parser()
    args = parser.parse_args(argv)
    # Do not serialize args directly; argparse contains func, which is a Python function.
    args.func(args)


if __name__ == "__main__":
    main()
