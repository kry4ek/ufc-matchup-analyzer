from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.features.mens_live_v3_bayes_features import (  # noqa: E402
    build_live_v3_bayes_feature_rows,
    candidate_v3_bayes_columns,
    prepare_live_v3_bayes_context,
)


META_COLUMNS = [
    "fight_id",
    "event_id",
    "event_date",
    "weight_class",
    "fighter_a_id",
    "fighter_b_id",
    "fighter_a",
    "fighter_b",
    "row_direction",
    "fighter_a_history_max_event_date_before",
    "fighter_b_history_max_event_date_before",
    "fighter_a_v2_history_max_event_date_before",
    "fighter_b_v2_history_max_event_date_before",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate live reconstruction parity for men v3 Bayesian smoothing candidate features.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--candidate-data", default="data/processed/mens_training_rows_v3_bayes_smoothing_candidate.csv")
    parser.add_argument("--raw-dir", default="data/raw/ufcstats_men")
    parser.add_argument("--out", default="data/validation/live_v3_bayes_smoothing_parity_sample.csv")
    parser.add_argument("--report", default="reports/live_v3_bayes_smoothing_parity_sample.md")
    parser.add_argument("--sample-size", type=int, default=None, help="Sample this many canonical fights. Omit with date filters to run all matching fights.")
    parser.add_argument("--start-date", default=None)
    parser.add_argument("--end-date", default=None)
    parser.add_argument("--tolerance", type=float, default=1e-8)
    parser.add_argument("--seed", type=int, default=42)
    return parser.parse_args()


def _jsonable(value: Any) -> Any:
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if np.isnan(value) else float(value)
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%d") if pd.notna(value) else None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return value


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()


def _numeric(value: Any) -> float:
    parsed = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    return float(parsed) if pd.notna(parsed) else np.nan


def _feature_type(feature: str) -> str:
    return "categorical" if feature.endswith("_prior_source") else "numeric"


def _feature_family(feature: str) -> str:
    for family in [
        "sig_str_acc",
        "sig_str_def",
        "total_str_acc",
        "total_str_def",
        "td_acc",
        "td_def",
    ]:
        if f"_{family}_" in feature:
            return family
    return "unknown"


def _feature_scope(feature: str) -> str:
    if feature.startswith("fighter_a_"):
        return "fighter_a_side"
    if feature.startswith("fighter_b_"):
        return "fighter_b_side"
    return "matchup_diff"


def read_candidate_data(path: Path, columns: list[str]) -> tuple[pd.DataFrame, list[str]]:
    if not path.exists():
        raise FileNotFoundError(path)
    header = pd.read_csv(path, nrows=0).columns.tolist()
    missing = [column for column in columns if column not in header]
    usecols = [column for column in META_COLUMNS + columns if column in header]
    data = pd.read_csv(path, usecols=usecols)
    return data, missing


def load_raw_data(raw_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    fights_path = raw_dir / "fights.csv"
    stats_path = raw_dir / "fight_stats.csv"
    if not fights_path.exists():
        raise FileNotFoundError(fights_path)
    if not stats_path.exists():
        raise FileNotFoundError(stats_path)
    return pd.read_csv(fights_path), pd.read_csv(stats_path)


def sample_canonical_rows(
    data: pd.DataFrame,
    *,
    sample_size: int | None,
    start_date: str | None,
    end_date: str | None,
    seed: int,
) -> pd.DataFrame:
    rows = data[data["row_direction"].astype(str) == "a_minus_b"].copy()
    rows["event_date"] = pd.to_datetime(rows["event_date"], errors="coerce")
    rows = rows[pd.notna(rows["event_date"])].copy()
    if start_date:
        rows = rows[rows["event_date"] >= pd.to_datetime(start_date)].copy()
    if end_date:
        rows = rows[rows["event_date"] <= pd.to_datetime(end_date)].copy()
    rows = rows.sort_values(["event_date", "fight_id"], kind="mergesort").reset_index(drop=True)
    if sample_size is not None and sample_size > 0 and len(rows) > sample_size:
        rows = rows.sample(n=sample_size, random_state=seed).sort_values(
            ["event_date", "fight_id"],
            kind="mergesort",
        )
    return rows.reset_index(drop=True)


def _stored_history_leakage_pass(row: pd.Series) -> bool:
    fight_date = pd.to_datetime(row.get("event_date"), errors="coerce")
    if pd.isna(fight_date):
        return False
    for column in [
        "fighter_a_history_max_event_date_before",
        "fighter_b_history_max_event_date_before",
        "fighter_a_v2_history_max_event_date_before",
        "fighter_b_v2_history_max_event_date_before",
    ]:
        if column not in row.index:
            continue
        history_date = pd.to_datetime(row.get(column), errors="coerce")
        if pd.notna(history_date) and history_date >= fight_date:
            return False
    return True


def compare_feature(
    *,
    source_row: pd.Series,
    live_row: dict[str, Any],
    feature: str,
    orientation: str,
    tolerance: float,
    warnings: list[str],
    leakage_pass: bool,
) -> dict[str, Any]:
    missing_feature = feature not in source_row.index or feature not in live_row
    stored = source_row.get(feature) if feature in source_row.index else np.nan
    live = live_row.get(feature) if feature in live_row else np.nan
    feature_type = _feature_type(feature)
    missing_value_mismatch = False
    exact_match = False
    within_tolerance = False
    delta = np.nan
    abs_delta = np.nan

    if missing_feature:
        status = "missing_feature"
    elif feature_type == "numeric":
        stored_num = _numeric(stored)
        live_num = _numeric(live)
        stored_missing = pd.isna(stored_num)
        live_missing = pd.isna(live_num)
        missing_value_mismatch = bool(stored_missing != live_missing)
        if stored_missing and live_missing:
            exact_match = True
            within_tolerance = True
        elif not missing_value_mismatch:
            delta = live_num - stored_num
            abs_delta = abs(delta)
            exact_match = bool(abs_delta == 0.0)
            within_tolerance = bool(abs_delta <= tolerance)
        status = "match" if within_tolerance else "mismatch"
    else:
        stored_missing = pd.isna(stored)
        live_missing = pd.isna(live)
        missing_value_mismatch = bool(stored_missing != live_missing)
        exact_match = bool((stored_missing and live_missing) or _clean_text(stored) == _clean_text(live))
        within_tolerance = exact_match and not missing_value_mismatch
        status = "match" if within_tolerance else "mismatch"

    return {
        "fight_id": source_row.get("fight_id", ""),
        "event_id": source_row.get("event_id", ""),
        "event_date": pd.to_datetime(source_row.get("event_date"), errors="coerce").strftime("%Y-%m-%d"),
        "fighter_a": source_row.get("fighter_a", ""),
        "fighter_b": source_row.get("fighter_b", ""),
        "fighter_a_id": source_row.get("fighter_a_id", ""),
        "fighter_b_id": source_row.get("fighter_b_id", ""),
        "row_direction": source_row.get("row_direction", ""),
        "orientation": orientation,
        "feature": feature,
        "feature_family": _feature_family(feature),
        "feature_scope": _feature_scope(feature),
        "feature_type": feature_type,
        "stored_value": _jsonable(stored),
        "live_value": _jsonable(live),
        "numeric_delta": _jsonable(delta),
        "abs_numeric_delta": _jsonable(abs_delta),
        "exact_match": bool(exact_match),
        "within_tolerance": bool(within_tolerance),
        "missing_value_mismatch": bool(missing_value_mismatch),
        "missing_feature": bool(missing_feature),
        "leakage_pass": bool(leakage_pass),
        "status": status,
        "warnings": "; ".join(dict.fromkeys(warnings)),
    }


def _error_row(source_row: pd.Series, orientation: str, message: str) -> dict[str, Any]:
    event_date = pd.to_datetime(source_row.get("event_date"), errors="coerce")
    return {
        "fight_id": source_row.get("fight_id", ""),
        "event_id": source_row.get("event_id", ""),
        "event_date": "" if pd.isna(event_date) else event_date.strftime("%Y-%m-%d"),
        "fighter_a": source_row.get("fighter_a", ""),
        "fighter_b": source_row.get("fighter_b", ""),
        "fighter_a_id": source_row.get("fighter_a_id", ""),
        "fighter_b_id": source_row.get("fighter_b_id", ""),
        "row_direction": source_row.get("row_direction", ""),
        "orientation": orientation,
        "feature": "__row_error__",
        "feature_family": "row_error",
        "feature_scope": "row_error",
        "feature_type": "error",
        "stored_value": "",
        "live_value": "",
        "numeric_delta": "",
        "abs_numeric_delta": "",
        "exact_match": False,
        "within_tolerance": False,
        "missing_value_mismatch": False,
        "missing_feature": False,
        "leakage_pass": False,
        "status": "error",
        "warnings": message,
    }


def build_comparisons(
    *,
    sampled: pd.DataFrame,
    mirrors: pd.DataFrame,
    columns: list[str],
    raw_fights: pd.DataFrame,
    raw_stats: pd.DataFrame,
    tolerance: float,
) -> pd.DataFrame:
    context = prepare_live_v3_bayes_context(raw_fights, raw_stats)
    mirror_by_fight = mirrors.set_index("fight_id", drop=False)
    rows: list[dict[str, Any]] = []

    for _, source_row in sampled.iterrows():
        fight_id = str(source_row.get("fight_id"))
        mirror_row = mirror_by_fight.loc[fight_id] if fight_id in mirror_by_fight.index else None
        if isinstance(mirror_row, pd.DataFrame):
            mirror_row = mirror_row.iloc[0]
        try:
            live_rows = build_live_v3_bayes_feature_rows(
                context=context,
                fighter_a=source_row.get("fighter_a"),
                fighter_b=source_row.get("fighter_b"),
                fighter_a_id=source_row.get("fighter_a_id"),
                fighter_b_id=source_row.get("fighter_b_id"),
                fight_date=source_row.get("event_date"),
                weight_class=_clean_text(source_row.get("weight_class")) or "Unknown",
            )
            stored_leakage_pass = _stored_history_leakage_pass(source_row)
            live_leakage_pass = bool(live_rows.leakage_audit.get("target_fight_stats_excluded"))
            leakage_pass = stored_leakage_pass and live_leakage_pass
            for feature in columns:
                rows.append(
                    compare_feature(
                        source_row=source_row,
                        live_row=live_rows.forward,
                        feature=feature,
                        orientation="forward",
                        tolerance=tolerance,
                        warnings=live_rows.warnings,
                        leakage_pass=leakage_pass,
                    )
                )
            if mirror_row is None:
                rows.append(_error_row(source_row, "reverse", "missing stored b_minus_a mirror row"))
                continue
            mirror_leakage_pass = _stored_history_leakage_pass(mirror_row) and live_leakage_pass
            for feature in columns:
                rows.append(
                    compare_feature(
                        source_row=mirror_row,
                        live_row=live_rows.reverse,
                        feature=feature,
                        orientation="reverse",
                        tolerance=tolerance,
                        warnings=live_rows.warnings,
                        leakage_pass=mirror_leakage_pass,
                    )
                )
        except Exception as exc:  # noqa: BLE001 - validation artifact should preserve row-level failures.
            rows.append(_error_row(source_row, "forward", f"{type(exc).__name__}: {exc}"))
    return pd.DataFrame(rows)


def _bool_series(series: pd.Series) -> pd.Series:
    if series.empty:
        return pd.Series([], dtype=bool)
    return series.astype(str).str.lower().isin(["true", "1", "yes"])


def _orientation_status(frame: pd.DataFrame, orientation: str) -> str:
    subset = frame[frame["orientation"] == orientation].copy()
    if subset.empty:
        return "FAIL"
    if (subset["status"] == "error").any() or _bool_series(subset["missing_feature"]).any():
        return "FAIL"
    mismatches = subset[subset["status"] == "mismatch"]
    numeric_mismatches = mismatches[mismatches["feature_type"] == "numeric"]
    categorical_mismatches = mismatches[mismatches["feature_type"] == "categorical"]
    if numeric_mismatches.empty and categorical_mismatches.empty:
        return "PASS"
    if numeric_mismatches.empty and not categorical_mismatches.empty:
        return "PARTIAL"
    return "FAIL"


def summarize_results(
    results: pd.DataFrame,
    *,
    requested_sample_size: int | None,
    selected_rows: int,
    columns: list[str],
    missing_candidate_columns: list[str],
    args: argparse.Namespace,
) -> dict[str, Any]:
    if results.empty:
        return {
            "status": "FAIL",
            "reason": "no comparison rows",
            "sampled_fights": 0,
            "compared_features": len(columns),
            "missing_feature_count": len(missing_candidate_columns),
        }

    match_rows = results[results["status"].isin(["match", "mismatch"])].copy()
    mismatches = match_rows[match_rows["status"] == "mismatch"].copy()
    numeric_mismatches = mismatches[mismatches["feature_type"] == "numeric"].copy()
    categorical_mismatches = mismatches[mismatches["feature_type"] == "categorical"].copy()
    row_errors = results[results["status"] == "error"].copy()
    missing_features = results[_bool_series(results["missing_feature"])].copy()
    leakage_pass = bool(not results.empty and _bool_series(results["leakage_pass"]).all())
    numeric_abs = pd.to_numeric(match_rows["abs_numeric_delta"], errors="coerce")
    forward_status = _orientation_status(results, "forward")
    reverse_status = _orientation_status(results, "reverse")

    if (
        selected_rows > 0
        and forward_status == "PASS"
        and reverse_status == "PASS"
        and leakage_pass
        and row_errors.empty
        and missing_features.empty
        and not missing_candidate_columns
    ):
        status = "PASS"
    elif (
        selected_rows > 0
        and forward_status in {"PASS", "PARTIAL"}
        and reverse_status in {"PASS", "PARTIAL"}
        and leakage_pass
        and numeric_mismatches.empty
        and row_errors.empty
        and missing_features.empty
        and not missing_candidate_columns
    ):
        status = "PARTIAL"
    else:
        status = "FAIL"

    by_feature = (
        mismatches.groupby(["orientation", "feature_type", "feature_family", "feature"], dropna=False)
        .agg(
            mismatches=("feature", "size"),
            max_abs_numeric_delta=("abs_numeric_delta", lambda values: pd.to_numeric(values, errors="coerce").max()),
        )
        .reset_index()
        .sort_values(["mismatches", "max_abs_numeric_delta", "feature"], ascending=[False, False, True], kind="mergesort")
        if not mismatches.empty
        else pd.DataFrame()
    )

    return {
        "status": status,
        "candidate_data": args.candidate_data,
        "raw_dir": args.raw_dir,
        "out": args.out,
        "report": args.report,
        "requested_sample_size": requested_sample_size if requested_sample_size is not None else "all matching",
        "start_date": args.start_date,
        "end_date": args.end_date,
        "tolerance": args.tolerance,
        "sampled_fights": int(selected_rows),
        "compared_features": int(len(columns)),
        "comparison_rows": int(len(match_rows)),
        "matched_comparison_rows": int((match_rows["status"] == "match").sum()),
        "numeric_mismatch_count": int(len(numeric_mismatches)),
        "categorical_mismatch_count": int(len(categorical_mismatches)),
        "prior_source_categorical_mismatch_count": int(
            categorical_mismatches["feature"].astype(str).str.endswith("_prior_source").sum()
        )
        if not categorical_mismatches.empty
        else 0,
        "missing_feature_count": int(len(missing_features) + len(missing_candidate_columns)),
        "missing_candidate_columns": missing_candidate_columns,
        "row_error_count": int(len(row_errors)),
        "max_abs_numeric_diff": None if numeric_abs.dropna().empty else float(numeric_abs.max()),
        "forward_orientation_result": forward_status,
        "reverse_orientation_result": reverse_status,
        "same_date_leakage_check": "PASS" if leakage_pass else "FAIL",
        "target_fight_leakage_check": "PASS" if leakage_pass else "FAIL",
        "leakage_pass": leakage_pass,
        "defaults_changed": False,
        "mismatches_by_feature": [
            {key: _jsonable(value) for key, value in row.items()}
            for row in by_feature.head(50).to_dict("records")
        ],
        "row_errors": [
            {key: _jsonable(value) for key, value in row.items()}
            for row in row_errors.head(20).to_dict("records")
        ],
    }


def markdown_table(rows: list[dict[str, Any]], columns: list[str], max_rows: int = 20) -> str:
    if not rows:
        return "_No rows._"
    lines = [
        "| " + " | ".join(columns) + " |",
        "| " + " | ".join("---" for _ in columns) + " |",
    ]
    for row in rows[:max_rows]:
        values = []
        for column in columns:
            value = row.get(column, "")
            if value is None:
                value = ""
            elif isinstance(value, float):
                value = f"{value:.12g}"
            values.append(str(value).replace("|", "\\|"))
        lines.append("| " + " | ".join(values) + " |")
    return "\n".join(lines)


def write_report(path: Path, summary: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Live v3 Bayesian Smoothing Parity Report",
        "",
        "## Summary",
        "",
        f"- Status: `{summary.get('status')}`",
        f"- Candidate data: `{summary.get('candidate_data')}`",
        f"- Raw dir: `{summary.get('raw_dir')}`",
        f"- Output CSV: `{summary.get('out')}`",
        f"- Requested sample size: `{summary.get('requested_sample_size')}`",
        f"- Date range: `{summary.get('start_date') or ''}` to `{summary.get('end_date') or ''}`",
        f"- Sampled fights: {summary.get('sampled_fights')}",
        f"- Candidate features compared: {summary.get('compared_features')}",
        f"- Comparison rows: {summary.get('comparison_rows')}",
        f"- Matched comparison rows: {summary.get('matched_comparison_rows')}",
        f"- Numeric mismatch count: {summary.get('numeric_mismatch_count')}",
        f"- Prior-source categorical mismatch count: {summary.get('prior_source_categorical_mismatch_count')}",
        f"- Missing feature count: {summary.get('missing_feature_count')}",
        f"- Row error count: {summary.get('row_error_count')}",
        f"- Max absolute numeric diff: {summary.get('max_abs_numeric_diff')}",
        f"- Forward orientation result: `{summary.get('forward_orientation_result')}`",
        f"- Reverse orientation result: `{summary.get('reverse_orientation_result')}`",
        f"- Same-date leakage check: `{summary.get('same_date_leakage_check')}`",
        f"- Target-fight leakage check: `{summary.get('target_fight_leakage_check')}`",
        f"- Defaults changed: `{summary.get('defaults_changed')}`",
        "",
        "## Interpretation",
        "",
        "This diagnostic reconstructs only the reporting-only candidate columns. It does not add the candidate to live prediction, model registry, full-card routing, or production defaults.",
        "",
        "## Mismatches By Feature",
        "",
        markdown_table(
            summary.get("mismatches_by_feature", []),
            ["orientation", "feature_type", "feature_family", "feature", "mismatches", "max_abs_numeric_delta"],
            50,
        ),
        "",
        "## Row Errors",
        "",
        markdown_table(
            summary.get("row_errors", []),
            ["fight_id", "event_date", "fighter_a", "fighter_b", "orientation", "warnings"],
            20,
        ),
        "",
    ]
    if summary.get("missing_candidate_columns"):
        lines.extend(
            [
                "## Missing Candidate Columns",
                "",
                "\n".join(f"- `{column}`" for column in summary["missing_candidate_columns"]),
                "",
            ]
        )
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    args = parse_args()
    candidate_path = Path(args.candidate_data)
    raw_dir = Path(args.raw_dir)
    out_path = Path(args.out)
    report_path = Path(args.report)
    columns = candidate_v3_bayes_columns()

    candidate_data, missing_candidate_columns = read_candidate_data(candidate_path, columns)
    sampled = sample_canonical_rows(
        candidate_data,
        sample_size=args.sample_size,
        start_date=args.start_date,
        end_date=args.end_date,
        seed=args.seed,
    )
    mirrors = candidate_data[candidate_data["row_direction"].astype(str) == "b_minus_a"].copy()
    raw_fights, raw_stats = load_raw_data(raw_dir)
    results = build_comparisons(
        sampled=sampled,
        mirrors=mirrors,
        columns=columns,
        raw_fights=raw_fights,
        raw_stats=raw_stats,
        tolerance=args.tolerance,
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    results.to_csv(out_path, index=False)

    summary = summarize_results(
        results,
        requested_sample_size=args.sample_size,
        selected_rows=len(sampled),
        columns=columns,
        missing_candidate_columns=missing_candidate_columns,
        args=args,
    )
    write_report(report_path, summary)
    print(json.dumps(summary, indent=2, default=_jsonable))
    return 0 if summary["status"] in {"PASS", "PARTIAL"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
