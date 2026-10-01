#!/usr/bin/env python3
"""
compute_live_bayes_smoothing_features_v1.py

Compute the 30 live Bayesian-smoothed prefight features that were added to:
  output_bayesian_prefight_smoothing_v1/ufc_womens_model_training_rows_advanced_plus_bayes_prefight_smoothing_v1.csv

The script is intentionally standalone and read-only. It does not modify training data or predictor files.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import numpy as np
import pandas as pd

SCRIPT_VERSION = "compute_live_bayes_smoothing_features_v1_2026_05_13"


@dataclass(frozen=True)
class SmoothPair:
    base: str
    numerator_col: str
    denominator_col: str


SMOOTH_PAIRS: List[SmoothPair] = [
    SmoothPair("career_sig_str_accuracy_before_bayes", "sig_str_landed_repaired", "sig_str_attempted_repaired"),
    SmoothPair("career_sig_str_allowed_accuracy_before_bayes", "opponent_sig_str_landed_repaired", "opponent_sig_str_attempted_repaired"),
    SmoothPair("career_total_str_accuracy_before_bayes", "total_str_landed", "total_str_attempted"),
    SmoothPair("career_total_str_allowed_accuracy_before_bayes", "opponent_total_str_landed", "opponent_total_str_attempted"),
    SmoothPair("career_td_accuracy_before_bayes", "td_landed", "td_attempted"),
    SmoothPair("career_td_allowed_accuracy_before_bayes", "opponent_td_landed", "opponent_td_attempted"),
]


FIGHTER_COL_CANDIDATES = ["fighter", "fighter_name", "name", "fighter_full_name"]
DATE_COL_CANDIDATES = ["event_date", "date", "fight_date"]
DIVISION_COL_CANDIDATES = ["division", "weight_class", "weightclass"]


class UserFacingError(Exception):
    pass


def norm_name(s: object) -> str:
    if pd.isna(s):
        return ""
    text = str(s).strip().lower()
    text = re.sub(r"[\u2018\u2019`´]", "'", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def safe_slug(s: str) -> str:
    s = norm_name(s).replace(" ", "_")
    return re.sub(r"[^a-z0-9_]+", "", s)[:80] or "unknown"


def find_first_col(cols: Iterable[str], candidates: Iterable[str], label: str) -> str:
    colset = {c.lower(): c for c in cols}
    for cand in candidates:
        if cand.lower() in colset:
            return colset[cand.lower()]
    raise UserFacingError(f"Could not detect {label} column. Tried: {list(candidates)}")


def require_columns(df: pd.DataFrame, cols: Iterable[str], context: str) -> None:
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise UserFacingError(f"{context} is missing required column(s): {missing}")


def to_numeric_series(df: pd.DataFrame, col: str) -> pd.Series:
    return pd.to_numeric(df[col], errors="coerce")


def parse_date_arg(date_text: str) -> pd.Timestamp:
    dt = pd.to_datetime(date_text, errors="coerce")
    if pd.isna(dt):
        raise UserFacingError(f"Could not parse --fight-date value: {date_text!r}")
    return pd.Timestamp(dt).normalize()


def load_stats(path: Path) -> Tuple[pd.DataFrame, Dict[str, str]]:
    if not path.exists():
        raise UserFacingError(f"Fighter-stats file does not exist: {path}")

    df = pd.read_csv(path)
    if df.empty:
        raise UserFacingError(f"Fighter-stats file is empty: {path}")

    fighter_col = find_first_col(df.columns, FIGHTER_COL_CANDIDATES, "fighter")
    date_col = find_first_col(df.columns, DATE_COL_CANDIDATES, "date")
    division_col = find_first_col(df.columns, DIVISION_COL_CANDIDATES, "division")

    required = [fighter_col, date_col, division_col]
    for pair in SMOOTH_PAIRS:
        required.extend([pair.numerator_col, pair.denominator_col])
    require_columns(df, required, "fighter-stats file")

    df = df.copy()
    df["__event_date"] = pd.to_datetime(df[date_col], errors="coerce").dt.normalize()
    df["__fighter_norm"] = df[fighter_col].map(norm_name)
    df["__division_norm"] = df[division_col].astype(str).map(lambda x: x.strip().lower())

    bad_dates = int(df["__event_date"].isna().sum())
    if bad_dates:
        print(f"WARNING: dropped {bad_dates} fighter-stat row(s) with unparseable dates.")
        df = df[df["__event_date"].notna()].copy()

    schema = {"fighter_col": fighter_col, "date_col": date_col, "division_col": division_col}
    return df, schema


def rate_from_sums(numerator_sum: float, denominator_sum: float, fallback: float) -> float:
    if denominator_sum > 0 and np.isfinite(denominator_sum):
        value = numerator_sum / denominator_sum
        if np.isfinite(value):
            return float(min(max(value, 0.0), 1.0))
    return float(fallback)


def compute_priors(
    hist_df: pd.DataFrame,
    division: str,
    prior_strength: float,
    min_group_denominator: float,
    neutral_prior: float,
) -> Tuple[Dict[str, float], List[Dict[str, object]]]:
    del prior_strength  # Only needed by caller; included in signature for manifest clarity.
    div_norm = str(division).strip().lower()
    prior_rates: Dict[str, float] = {}
    audit_rows: List[Dict[str, object]] = []

    for pair in SMOOTH_PAIRS:
        num = to_numeric_series(hist_df, pair.numerator_col)
        den = to_numeric_series(hist_df, pair.denominator_col)
        valid = den.notna() & num.notna() & (den >= 0) & (num >= 0) & (num <= den)

        global_num = float(num[valid].sum()) if valid.any() else 0.0
        global_den = float(den[valid].sum()) if valid.any() else 0.0
        global_rate = rate_from_sums(global_num, global_den, neutral_prior)

        div_mask = valid & (hist_df["__division_norm"] == div_norm)
        div_num = float(num[div_mask].sum()) if div_mask.any() else 0.0
        div_den = float(den[div_mask].sum()) if div_mask.any() else 0.0
        div_rate = rate_from_sums(div_num, div_den, global_rate)

        use_group = div_den >= min_group_denominator
        chosen = div_rate if use_group else global_rate
        if not np.isfinite(chosen):
            chosen = neutral_prior
        chosen = float(min(max(chosen, 0.0), 1.0))

        prior_rates[pair.base] = chosen
        audit_rows.append({
            "feature_base": pair.base,
            "numerator_col": pair.numerator_col,
            "denominator_col": pair.denominator_col,
            "global_numerator_sum_before_date": global_num,
            "global_denominator_sum_before_date": global_den,
            "global_prior_rate": global_rate,
            "division": division,
            "division_numerator_sum_before_date": div_num,
            "division_denominator_sum_before_date": div_den,
            "division_prior_rate": div_rate,
            "min_group_denominator": min_group_denominator,
            "used_prior_source": "division" if use_group else "global",
            "chosen_prior_rate": chosen,
        })

    return prior_rates, audit_rows


def fighter_history(df_before: pd.DataFrame, fighter_name: str) -> pd.DataFrame:
    n = norm_name(fighter_name)
    return df_before[df_before["__fighter_norm"] == n].copy()


def name_suggestions(df: pd.DataFrame, fighter_name: str, limit: int = 10) -> List[str]:
    target_tokens = set(norm_name(fighter_name).split())
    if not target_tokens:
        return []
    names = sorted(str(x) for x in df.loc[df["__fighter_norm"].ne(""), df.attrs.get("fighter_col", "fighter")].dropna().unique())
    scored = []
    for name in names:
        toks = set(norm_name(name).split())
        if not toks:
            continue
        score = len(target_tokens & toks) / len(target_tokens | toks)
        if score > 0:
            scored.append((score, name))
    scored.sort(reverse=True)
    return [n for _, n in scored[:limit]]


def compute_side_features(
    side: str,
    fighter_name: str,
    hist: pd.DataFrame,
    prior_rates: Dict[str, float],
    prior_strength: float,
    suffix: str,
    fighter_col: str,
) -> Tuple[Dict[str, float], Dict[str, object]]:
    out: Dict[str, float] = {}
    audit: Dict[str, object] = {
        "side": side,
        "fighter": fighter_name,
        "matched_rows_before_date": int(len(hist)),
        "first_prior_fight_date": None,
        "last_prior_fight_date": None,
        "matched_name_variants": [],
    }

    if len(hist):
        audit["first_prior_fight_date"] = str(hist["__event_date"].min().date())
        audit["last_prior_fight_date"] = str(hist["__event_date"].max().date())
        audit["matched_name_variants"] = sorted(str(x) for x in hist[fighter_col].dropna().unique())

    for pair in SMOOTH_PAIRS:
        num = to_numeric_series(hist, pair.numerator_col) if len(hist) else pd.Series(dtype=float)
        den = to_numeric_series(hist, pair.denominator_col) if len(hist) else pd.Series(dtype=float)
        valid = den.notna() & num.notna() & (den >= 0) & (num >= 0) & (num <= den)

        num_sum = float(num[valid].sum()) if valid.any() else 0.0
        den_sum = float(den[valid].sum()) if valid.any() else 0.0
        prior_rate = prior_rates[pair.base]
        smoothed = (num_sum + prior_strength * prior_rate) / (den_sum + prior_strength)
        smoothed = float(min(max(smoothed, 0.0), 1.0))

        value_col = f"{side}_{pair.base}_{suffix}"
        den_col = f"{side}_{pair.base}_{suffix}_den_before"
        out[value_col] = smoothed
        out[den_col] = den_sum

        audit[f"{pair.base}_num_before"] = num_sum
        audit[f"{pair.base}_den_before"] = den_sum
        audit[f"{pair.base}_prior_rate"] = prior_rate
        audit[f"{pair.base}_smoothed"] = smoothed

    return out, audit


def compute_features(args: argparse.Namespace) -> int:
    stats_path = Path(args.fighter_stats)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    fight_date = parse_date_arg(args.fight_date)
    df, schema = load_stats(stats_path)
    df.attrs["fighter_col"] = schema["fighter_col"]

    # Strict no-leakage cutoff: only fights strictly before the requested fight date.
    before = df[df["__event_date"] < fight_date].copy()
    on_or_after_count = int((df["__event_date"] >= fight_date).sum())

    prior_rates, prior_audit_rows = compute_priors(
        before,
        division=args.division,
        prior_strength=args.prior_strength,
        min_group_denominator=args.min_group_denominator,
        neutral_prior=args.neutral_prior,
    )

    hist_a = fighter_history(before, args.fighter_a)
    hist_b = fighter_history(before, args.fighter_b)

    suffix = f"s{int(args.prior_strength) if float(args.prior_strength).is_integer() else str(args.prior_strength).replace('.', 'p')}"
    side_a, audit_a = compute_side_features(
        "fighter_a", args.fighter_a, hist_a, prior_rates, args.prior_strength, suffix, schema["fighter_col"]
    )
    side_b, audit_b = compute_side_features(
        "fighter_b", args.fighter_b, hist_b, prior_rates, args.prior_strength, suffix, schema["fighter_col"]
    )

    features: Dict[str, float] = {}
    features.update(side_a)
    features.update(side_b)

    for pair in SMOOTH_PAIRS:
        a_col = f"fighter_a_{pair.base}_{suffix}"
        b_col = f"fighter_b_{pair.base}_{suffix}"
        diff_col = f"{pair.base}_{suffix}_diff"
        features[diff_col] = float(features[a_col] - features[b_col])

    expected_cols = []
    for side in ["fighter_a", "fighter_b"]:
        for pair in SMOOTH_PAIRS:
            expected_cols.append(f"{side}_{pair.base}_{suffix}")
        for pair in SMOOTH_PAIRS:
            expected_cols.append(f"{side}_{pair.base}_{suffix}_den_before")
    for pair in SMOOTH_PAIRS:
        expected_cols.append(f"{pair.base}_{suffix}_diff")

    missing_expected = [c for c in expected_cols if c not in features]
    extra = [c for c in features if c not in expected_cols]
    if missing_expected or extra:
        raise UserFacingError(f"Internal feature set mismatch. Missing={missing_expected}, extra={extra}")

    # Safety checks.
    value_cols = [c for c in expected_cols if c.endswith(f"_{suffix}") and not c.endswith("_diff")]
    denom_cols = [c for c in expected_cols if c.endswith("_den_before")]
    diff_cols = [c for c in expected_cols if c.endswith("_diff")]

    bad_values = {c: features[c] for c in value_cols if not (0.0 <= features[c] <= 1.0)}
    bad_denoms = {c: features[c] for c in denom_cols if not (features[c] >= 0.0)}
    bad_diffs = {c: features[c] for c in diff_cols if not (-1.0 <= features[c] <= 1.0)}
    if bad_values or bad_denoms or bad_diffs:
        raise UserFacingError(
            "Computed feature safety check failed: "
            f"bad_values={bad_values}, bad_denoms={bad_denoms}, bad_diffs={bad_diffs}"
        )

    base_slug = f"{safe_slug(args.fighter_a)}_vs_{safe_slug(args.fighter_b)}_{fight_date.date()}"
    csv_path = out_dir / f"live_bayes_smoothing_features_{base_slug}.csv"
    json_path = out_dir / f"live_bayes_smoothing_features_{base_slug}.json"
    prior_path = out_dir / f"live_bayes_smoothing_priors_{base_slug}.csv"
    audit_path = out_dir / f"live_bayes_smoothing_audit_{base_slug}.txt"

    row = {
        "fighter_a": args.fighter_a,
        "fighter_b": args.fighter_b,
        "division": args.division,
        "fight_date": str(fight_date.date()),
        **{c: features[c] for c in expected_cols},
    }
    pd.DataFrame([row]).to_csv(csv_path, index=False)
    pd.DataFrame(prior_audit_rows).to_csv(prior_path, index=False)

    manifest = {
        "script_version": SCRIPT_VERSION,
        "fighter_a": args.fighter_a,
        "fighter_b": args.fighter_b,
        "division": args.division,
        "fight_date": str(fight_date.date()),
        "fighter_stats": str(stats_path),
        "schema": schema,
        "prior_strength": args.prior_strength,
        "min_group_denominator": args.min_group_denominator,
        "neutral_prior": args.neutral_prior,
        "rows_in_stats_file": int(len(df)),
        "rows_before_fight_date_used_for_priors": int(len(before)),
        "rows_on_or_after_fight_date_excluded": on_or_after_count,
        "features_count": len(expected_cols),
        "value_cols_count": len(value_cols),
        "denominator_before_cols_count": len(denom_cols),
        "diff_cols_count": len(diff_cols),
        "fighter_a_audit": audit_a,
        "fighter_b_audit": audit_b,
        "features": {c: features[c] for c in expected_cols},
    }
    json_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    lines = []
    lines.append(f"Script version: {SCRIPT_VERSION}")
    lines.append(f"Fighter A: {args.fighter_a}")
    lines.append(f"Fighter B: {args.fighter_b}")
    lines.append(f"Division: {args.division}")
    lines.append(f"Fight date: {fight_date.date()}")
    lines.append(f"Fighter-stats file: {stats_path}")
    lines.append(f"Rows in fighter-stats file: {len(df)}")
    lines.append(f"Rows before fight date used for priors/features: {len(before)}")
    lines.append(f"Rows on/after fight date excluded for no-leakage: {on_or_after_count}")
    lines.append(f"Detected fighter column: {schema['fighter_col']}")
    lines.append(f"Detected date column: {schema['date_col']}")
    lines.append(f"Detected division column: {schema['division_col']}")
    lines.append(f"Prior strength: {args.prior_strength}")
    lines.append(f"Min group denominator: {args.min_group_denominator}")
    lines.append("")
    lines.append("Feature counts:")
    lines.append(f"  total expected/live features: {len(expected_cols)}")
    lines.append(f"  value columns: {len(value_cols)}")
    lines.append(f"  denominator-before columns: {len(denom_cols)}")
    lines.append(f"  diff columns: {len(diff_cols)}")
    lines.append("")
    for audit in [audit_a, audit_b]:
        lines.append(f"{audit['side']} history:")
        lines.append(f"  fighter: {audit['fighter']}")
        lines.append(f"  matched rows before date: {audit['matched_rows_before_date']}")
        lines.append(f"  first prior fight date: {audit['first_prior_fight_date']}")
        lines.append(f"  last prior fight date: {audit['last_prior_fight_date']}")
        lines.append(f"  matched name variants: {audit['matched_name_variants']}")
        if audit["matched_rows_before_date"] == 0:
            lines.append("  NOTE: no prior UFC rows found before this date; smoothed rates equal prior rates and den_before=0.")
        lines.append("")
    lines.append("Safety checks:")
    lines.append(f"  value columns in [0,1]: {len(bad_values) == 0}")
    lines.append(f"  denominator-before columns nonnegative: {len(bad_denoms) == 0}")
    lines.append(f"  diff columns in [-1,1]: {len(bad_diffs) == 0}")
    lines.append("  no-leakage cutoff: used only event_date < fight_date")
    lines.append("")
    lines.append("Output files:")
    lines.append(f"  - {csv_path}")
    lines.append(f"  - {json_path}")
    lines.append(f"  - {prior_path}")
    audit_path.write_text("\n".join(lines), encoding="utf-8")

    print(f"Script version: {SCRIPT_VERSION}")
    print(f"Computed {len(expected_cols)} Bayesian-smoothed live features.")
    print(f"Fighter A matched rows before date: {audit_a['matched_rows_before_date']}")
    print(f"Fighter B matched rows before date: {audit_b['matched_rows_before_date']}")
    print(f"Rows before fight date used: {len(before)}")
    print(f"Rows on/after fight date excluded: {on_or_after_count}")
    print("Safety checks: PASS")
    print(f"Saved features CSV: {csv_path}")
    print(f"Saved manifest JSON: {json_path}")
    print(f"Saved prior audit CSV: {prior_path}")
    print(f"Saved audit text: {audit_path}")

    if args.print_features:
        print("\nLive feature row:")
        for c in expected_cols:
            print(f"  {c}: {features[c]}")

    return 0


def inspect_stats(args: argparse.Namespace) -> int:
    df, schema = load_stats(Path(args.fighter_stats))
    print(f"Script version: {SCRIPT_VERSION}")
    print(f"Fighter-stats file: {args.fighter_stats}")
    print(f"Rows: {len(df):,}; columns: {len(df.columns):,}")
    print("Detected schema:")
    print(json.dumps(schema, indent=2))
    print("Required smoothing pairs:")
    for pair in SMOOTH_PAIRS:
        print(f"  - {pair.base}: {pair.numerator_col} / {pair.denominator_col}")
    print("Schema status: OK")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Compute live Bayesian-smoothed prefight features for UFC women's matchup prediction.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_inspect = sub.add_parser("inspect", help="Inspect fighter-stats schema and required columns.")
    p_inspect.add_argument("--fighter-stats", required=True)
    p_inspect.set_defaults(func=inspect_stats)

    p_compute = sub.add_parser("compute", help="Compute the 30 live Bayesian smoothing features for one matchup.")
    p_compute.add_argument("--fighter-a", required=True)
    p_compute.add_argument("--fighter-b", required=True)
    p_compute.add_argument("--division", required=True)
    p_compute.add_argument("--fight-date", required=True, help="YYYY-MM-DD")
    p_compute.add_argument("--fighter-stats", required=True)
    p_compute.add_argument("--out-dir", default="output_live_bayes_smoothing_features_v1")
    p_compute.add_argument("--prior-strength", type=float, default=20.0)
    p_compute.add_argument("--min-group-denominator", type=float, default=200.0)
    p_compute.add_argument("--neutral-prior", type=float, default=0.5)
    p_compute.add_argument("--print-features", action="store_true")
    p_compute.set_defaults(func=compute_features)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return int(args.func(args))
    except UserFacingError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
