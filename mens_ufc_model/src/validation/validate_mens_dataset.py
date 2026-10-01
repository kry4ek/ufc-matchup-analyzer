from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


TARGET_COLUMNS = {
    "fighter_a_won",
    "won",
    "fighter_a_result",
    "fighter_b_result",
    "result",
    "winner_id",
    "loser_id",
}

NON_FEATURE_COLUMNS = {
    "fight_id",
    "event_id",
    "event_date",
    "fighter_a_id",
    "fighter_b_id",
    "fighter_a",
    "fighter_b",
    "fighter_a_result",
    "fighter_b_result",
    "fighter_a_won",
    "method",
    "round",
    "time",
    "row_direction",
    "fighter_a_history_max_event_date_before",
    "fighter_b_history_max_event_date_before",
}

CURRENT_FIGHT_STAT_COLUMNS = {
    "knockdowns",
    "significant_strikes_landed",
    "significant_strikes_attempted",
    "total_strikes_landed",
    "total_strikes_attempted",
    "takedowns_landed",
    "takedowns_attempted",
    "submission_attempts",
    "reversals",
    "control_time_seconds",
    "head_significant_strikes_landed",
    "head_significant_strikes_attempted",
    "body_significant_strikes_landed",
    "body_significant_strikes_attempted",
    "leg_significant_strikes_landed",
    "leg_significant_strikes_attempted",
    "distance_significant_strikes_landed",
    "distance_significant_strikes_attempted",
    "clinch_significant_strikes_landed",
    "clinch_significant_strikes_attempted",
    "ground_significant_strikes_landed",
    "ground_significant_strikes_attempted",
    "elapsed_seconds",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate normalized men's UFC dataset outputs.")
    parser.add_argument("--raw-dir", default="data/raw/ufcstats_men", help="Folder with normalized raw CSVs.")
    parser.add_argument("--training", default="data/processed/mens_training_rows.csv", help="Training rows CSV.")
    parser.add_argument(
        "--out",
        default="data/processed/mens_validation_summary.json",
        help="JSON validation summary path.",
    )
    parser.add_argument(
        "--allow-mirrored",
        action="store_true",
        help="Allow two training rows per fight when row_direction marks mirrored rows.",
    )
    return parser.parse_args()


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(path)
    return pd.read_csv(path)


def read_optional_csv(path: Path) -> pd.DataFrame | None:
    if not path.exists():
        return None
    return pd.read_csv(path)


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def json_ready(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): json_ready(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_ready(item) for item in value]
    if isinstance(value, tuple):
        return [json_ready(item) for item in value]
    if value is pd.NA or value is pd.NaT:
        return None
    if hasattr(value, "item") and not isinstance(value, (str, bytes)):
        try:
            return json_ready(value.item())
        except (AttributeError, ValueError, TypeError):
            pass
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return value


def pct(numerator: int | float, denominator: int | float) -> float:
    if not denominator:
        return 0.0
    return round(float(numerator) / float(denominator) * 100.0, 4)


def missing_mask(series: pd.Series) -> pd.Series:
    text = series.astype(str).str.strip()
    return series.isna() | text.isin({"", "nan", "NaN", "None", "NaT", "--", "---"})


def missing_summary(df: pd.DataFrame, column: str) -> dict[str, Any]:
    total = int(len(df))
    if column not in df.columns:
        return {"count": total, "percentage": 100.0 if total else 0.0, "column_present": False}
    missing = int(missing_mask(df[column]).sum())
    return {"count": missing, "percentage": pct(missing, total), "column_present": True}


def count_contains(series: pd.Series, pattern: str) -> int:
    return int(series.fillna("").astype(str).str.contains(pattern, case=False, regex=False).sum())


def value_counts_dict(series: pd.Series) -> dict[str, int]:
    counts = series.fillna("Unknown").astype(str).replace("", "Unknown").value_counts().sort_index()
    return {str(key): int(value) for key, value in counts.items()}


def year_counts(date_series: pd.Series) -> dict[str, int]:
    dates = pd.to_datetime(date_series, errors="coerce")
    years = dates.dt.year.dropna().astype(int).astype(str)
    return {str(key): int(value) for key, value in years.value_counts().sort_index().items()}


def date_range(date_series: pd.Series) -> dict[str, Any]:
    dates = pd.to_datetime(date_series, errors="coerce")
    return {
        "valid_dates": int(dates.notna().sum()),
        "invalid_dates": int(dates.isna().sum()),
        "min": "" if dates.dropna().empty else dates.min().strftime("%Y-%m-%d"),
        "max": "" if dates.dropna().empty else dates.max().strftime("%Y-%m-%d"),
    }


def first_items(series: pd.Series, limit: int = 20) -> list[str]:
    return [str(value) for value in series.dropna().astype(str).head(limit).tolist()]


def infer_related_paths(training_path: Path) -> dict[str, Path]:
    processed_dir = training_path.parent
    project_root = processed_dir.parent.parent if processed_dir.name == "processed" else ROOT
    stem = training_path.stem
    sample_suffix = "_sample" if stem.endswith("_sample") else ""
    return {
        "prefight": project_root / "data" / "interim" / f"mens_prefight_snapshots{sample_suffix}.csv",
        "matchups": project_root / "data" / "interim" / f"mens_model_ready_matchups{sample_suffix}.csv",
        "manifest": training_path.with_suffix(".manifest.json"),
    }


def duplicate_id_summary(df: pd.DataFrame, columns: str | list[str]) -> dict[str, Any]:
    if isinstance(columns, str):
        columns = [columns]
    if not set(columns).issubset(df.columns):
        return {"count": 0, "columns_present": False, "examples": []}
    duplicated = df.duplicated(columns, keep=False)
    examples = df.loc[duplicated, columns].drop_duplicates().head(20)
    return {
        "count": int(df.duplicated(columns).sum()),
        "columns_present": True,
        "examples": examples.astype(str).to_dict("records"),
    }


def mirrored_integrity_summary(training: pd.DataFrame, allow_mirrored: bool) -> dict[str, Any]:
    if "fight_id" not in training.columns:
        return {"status": "missing_fight_id", "passed": False}

    counts = training["fight_id"].astype(str).value_counts()
    duplicate_fights = counts[counts > 1]
    summary: dict[str, Any] = {
        "status": "checked",
        "duplicate_fight_ids": int(len(duplicate_fights)),
        "max_rows_per_fight_id": int(counts.max()) if not counts.empty else 0,
        "allowed_as_mirrored": bool(allow_mirrored),
        "unexpected_duplicate_fight_ids": int(len(duplicate_fights)),
        "bad_direction_groups": 0,
        "bad_identity_swap_groups": 0,
        "bad_target_complement_groups": 0,
        "bad_diff_mirror_groups": 0,
        "missing_pair_groups": 0,
        "passed": False,
    }
    if not allow_mirrored:
        summary["passed"] = int(len(duplicate_fights)) == 0
        return summary
    if "row_direction" not in training.columns:
        summary["status"] = "missing_row_direction"
        return summary

    expected_dirs = {"a_minus_b", "b_minus_a"}
    diff_cols = [col for col in training.columns if col.endswith("_diff")]
    unexpected = 0
    bad_direction = 0
    bad_swap = 0
    bad_target = 0
    bad_diff = 0
    missing_pair = 0

    for _, group in training.groupby("fight_id", dropna=False):
        if len(group) != 2:
            unexpected += 1
            missing_pair += 1
            continue
        dirs = set(group["row_direction"].dropna().astype(str))
        if dirs != expected_dirs:
            unexpected += 1
            bad_direction += 1
            continue
        forward = group[group["row_direction"].astype(str) == "a_minus_b"].iloc[0]
        reverse = group[group["row_direction"].astype(str) == "b_minus_a"].iloc[0]

        if {"fighter_a_id", "fighter_b_id"}.issubset(training.columns):
            swap_ok = (
                str(forward.get("fighter_a_id")) == str(reverse.get("fighter_b_id"))
                and str(forward.get("fighter_b_id")) == str(reverse.get("fighter_a_id"))
            )
            if not swap_ok:
                unexpected += 1
                bad_swap += 1

        if "fighter_a_won" in training.columns:
            f_target = pd.to_numeric(pd.Series([forward.get("fighter_a_won")]), errors="coerce").iloc[0]
            r_target = pd.to_numeric(pd.Series([reverse.get("fighter_a_won")]), errors="coerce").iloc[0]
            if pd.notna(f_target) and pd.notna(r_target) and int(f_target) + int(r_target) != 1:
                unexpected += 1
                bad_target += 1

        for col in diff_cols:
            f_value = pd.to_numeric(pd.Series([forward.get(col)]), errors="coerce").iloc[0]
            r_value = pd.to_numeric(pd.Series([reverse.get(col)]), errors="coerce").iloc[0]
            if pd.isna(f_value) and pd.isna(r_value):
                continue
            if pd.isna(f_value) != pd.isna(r_value) or abs(float(f_value) + float(r_value)) > 1e-9:
                unexpected += 1
                bad_diff += 1
                break

    summary.update(
        {
            "unexpected_duplicate_fight_ids": int(unexpected),
            "bad_direction_groups": int(bad_direction),
            "bad_identity_swap_groups": int(bad_swap),
            "bad_target_complement_groups": int(bad_target),
            "bad_diff_mirror_groups": int(bad_diff),
            "missing_pair_groups": int(missing_pair),
            "passed": int(unexpected) == 0,
        }
    )
    return summary


def prefight_leakage_violations(training: pd.DataFrame) -> dict[str, Any]:
    if "event_date" not in training.columns:
        return {"total": 0, "columns_checked": [], "by_column": {}, "event_date_present": False}
    event_dates = pd.to_datetime(training["event_date"], errors="coerce")
    total = 0
    by_column: dict[str, int] = {}
    checked: list[str] = []
    for col in [
        "fighter_a_history_max_event_date_before",
        "fighter_b_history_max_event_date_before",
    ]:
        if col not in training.columns:
            continue
        checked.append(col)
        history_dates = pd.to_datetime(training[col], errors="coerce")
        violations = int((history_dates.notna() & event_dates.notna() & (history_dates >= event_dates)).sum())
        by_column[col] = violations
        total += violations
    return {
        "total": int(total),
        "columns_checked": checked,
        "by_column": by_column,
        "event_date_present": True,
    }


def candidate_feature_columns(training: pd.DataFrame) -> list[str]:
    columns: list[str] = []
    for col in training.columns:
        if col in NON_FEATURE_COLUMNS:
            continue
        if col in TARGET_COLUMNS:
            continue
        columns.append(col)
    return columns


def current_fight_stat_features(feature_columns: list[str]) -> list[str]:
    suspicious = []
    for col in feature_columns:
        base = col
        for prefix in ("fighter_a_", "fighter_b_", "opponent_"):
            if base.startswith(prefix):
                base = base[len(prefix) :]
        if base in CURRENT_FIGHT_STAT_COLUMNS:
            suspicious.append(col)
    return suspicious


def feature_usability(
    column: str,
    is_numeric: bool,
    missing_percentage: float,
    zero_percentage: float,
    unique_values: int,
) -> tuple[str, str]:
    if unique_values <= 1:
        return "no", "constant or empty"
    if missing_percentage >= 99.5:
        return "no", "effectively all missing"
    if missing_percentage > 60.0:
        return "review", "high missingness"
    if is_numeric and zero_percentage > 95.0:
        return "review", "zero-heavy numeric feature"
    if column.endswith("_diff") or column in {"weight_class", "stance_matchup", "is_catchweight_or_openweight"}:
        return "yes", "direct model feature candidate"
    return "review", "leakage-safe paired feature; likely redundant with diff feature"


def build_feature_completeness(training: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    total = int(len(training))
    for col in candidate_feature_columns(training):
        series = training[col]
        missing = missing_mask(series)
        missing_count = int(missing.sum())
        numeric = pd.to_numeric(series, errors="coerce")
        numeric_non_missing = numeric[~missing & numeric.notna()]
        is_numeric = int(numeric.notna().sum()) > 0 and int((numeric.notna() | missing).sum()) == total
        if is_numeric:
            zero_count = int((numeric_non_missing == 0).sum())
            min_value = float(numeric_non_missing.min()) if not numeric_non_missing.empty else None
            max_value = float(numeric_non_missing.max()) if not numeric_non_missing.empty else None
            mean_value = float(numeric_non_missing.mean()) if not numeric_non_missing.empty else None
        else:
            text = series[~missing].astype(str).str.strip()
            zero_count = int(text.isin({"0", "0.0"}).sum())
            min_value = None
            max_value = None
            mean_value = None
        missing_percentage = pct(missing_count, total)
        zero_percentage = pct(zero_count, total - missing_count)
        usable, notes = feature_usability(
            col,
            is_numeric,
            missing_percentage,
            zero_percentage,
            int(series[~missing].nunique(dropna=True)),
        )
        rows.append(
            {
                "feature_column": col,
                "dtype": str(series.dtype),
                "missing_count": missing_count,
                "missing_percentage": missing_percentage,
                "zero_count": zero_count,
                "zero_percentage": zero_percentage,
                "min": min_value,
                "max": max_value,
                "mean": mean_value,
                "unique_values": int(series[~missing].nunique(dropna=True)),
                "usable_for_sprint3_modeling": usable,
                "notes": notes,
            }
        )
    return pd.DataFrame(rows)


def outcome_summary(fights: pd.DataFrame, matchups: pd.DataFrame | None, allow_mirrored: bool) -> dict[str, Any]:
    result_series = fights.get("result", pd.Series(dtype=str)).fillna("").astype(str).str.lower()
    draw_count = int((result_series == "draw").sum())
    no_contest_count = int((result_series == "no_contest").sum())
    unknown_count = int((result_series == "unknown").sum())
    non_binary_fights = int((~result_series.isin(["win_loss"])).sum())

    invalid_matchups = None
    rows_excluded = non_binary_fights * (2 if allow_mirrored else 1)
    if matchups is not None and "fighter_a_won" in matchups.columns:
        targets = pd.to_numeric(matchups["fighter_a_won"], errors="coerce")
        invalid_matchups = int((~targets.isin([0, 1])).sum())
        rows_excluded = invalid_matchups * (2 if allow_mirrored else 1)

    return {
        "draw_fights": draw_count,
        "no_contest_fights": no_contest_count,
        "unknown_result_fights": unknown_count,
        "draw_or_no_contest_fights": draw_count + no_contest_count,
        "non_binary_fights": non_binary_fights,
        "invalid_matchups_before_binary_drop": invalid_matchups,
        "rows_excluded_from_binary_training": int(rows_excluded),
    }


def stat_row_integrity(fights: pd.DataFrame, fight_stats: pd.DataFrame) -> dict[str, Any]:
    out: dict[str, Any] = {
        "duplicate_fight_fighter_rows": duplicate_id_summary(fight_stats, ["fight_id", "fighter_id"]),
        "fight_stat_rows_per_fight_not_two": 0,
        "fights_missing_stat_rows": 0,
        "fight_stats_for_unknown_fights": 0,
    }
    if "fight_id" not in fight_stats.columns or "fight_id" not in fights.columns:
        return out
    rows_per_fight = fight_stats["fight_id"].astype(str).value_counts()
    out["fight_stat_rows_per_fight_not_two"] = int((rows_per_fight != 2).sum())
    fight_ids = set(fights["fight_id"].dropna().astype(str))
    stat_fight_ids = set(fight_stats["fight_id"].dropna().astype(str))
    out["fights_missing_stat_rows"] = int(len(fight_ids - stat_fight_ids))
    out["fight_stats_for_unknown_fights"] = int(len(stat_fight_ids - fight_ids))
    return out


def profile_identity_summary(fighters: pd.DataFrame) -> dict[str, Any]:
    if fighters.empty or not {"fighter_id", "fighter_name"}.issubset(fighters.columns):
        return {
            "max_names_per_fighter_id": 0,
            "max_ids_per_fighter_name": 0,
            "duplicate_name_examples": [],
        }
    names_per_id = fighters.groupby("fighter_id")["fighter_name"].nunique(dropna=True)
    ids_per_name = fighters.groupby("fighter_name")["fighter_id"].nunique(dropna=True)
    duplicate_names = ids_per_name[ids_per_name > 1].sort_values(ascending=False).head(20)
    return {
        "max_names_per_fighter_id": int(names_per_id.max()) if not names_per_id.empty else 0,
        "max_ids_per_fighter_name": int(ids_per_name.max()) if not ids_per_name.empty else 0,
        "duplicate_name_examples": [
            {"fighter_name": str(name), "fighter_id_count": int(count)}
            for name, count in duplicate_names.items()
        ],
    }


def ingest_issue_summary(manifest: dict[str, Any]) -> dict[str, Any]:
    issues = manifest.get("issues") or []
    if not isinstance(issues, list):
        issues = []
    by_stage: dict[str, int] = {}
    for issue in issues:
        if isinstance(issue, dict):
            stage = str(issue.get("stage") or "unknown")
        else:
            stage = "unknown"
        by_stage[stage] = by_stage.get(stage, 0) + 1
    return {
        "manifest_present": bool(manifest),
        "issue_count": int(len(issues)),
        "issues_by_stage": by_stage,
        "issue_samples": issues[:20],
        "manifest_fields": {key: value for key, value in manifest.items() if key != "issues"},
    }


def validate(raw_dir: Path, training_path: Path, allow_mirrored: bool) -> tuple[dict[str, Any], pd.DataFrame]:
    events = read_csv(raw_dir / "events.csv")
    fights = read_csv(raw_dir / "fights.csv")
    fight_stats = read_csv(raw_dir / "fight_stats.csv")
    fighters = read_csv(raw_dir / "fighters.csv")
    training = read_csv(training_path)

    related_paths = infer_related_paths(training_path)
    prefight = read_optional_csv(related_paths["prefight"])
    matchups = read_optional_csv(related_paths["matchups"])
    build_manifest = read_json(related_paths["manifest"])
    ingest_manifest = read_json(raw_dir / "ingest_manifest.json")

    same_fighter_fights = 0
    if {"fighter_red_id", "fighter_blue_id"}.issubset(fights.columns):
        same_fighter_fights = int(
            (
                fights["fighter_red_id"].fillna("").astype(str)
                == fights["fighter_blue_id"].fillna("").astype(str)
            ).sum()
        )
    same_fighter_training = 0
    if {"fighter_a_id", "fighter_b_id"}.issubset(training.columns):
        same_fighter_training = int(
            (
                training["fighter_a_id"].fillna("").astype(str)
                == training["fighter_b_id"].fillna("").astype(str)
            ).sum()
        )

    target_invalid = 0
    if "fighter_a_won" in training.columns:
        targets = pd.to_numeric(training["fighter_a_won"], errors="coerce")
        target_invalid = int((~targets.isin([0, 1])).sum())

    feature_completeness = build_feature_completeness(training)
    feature_columns = feature_completeness["feature_column"].tolist() if not feature_completeness.empty else []
    leakage_history = prefight_leakage_violations(training)
    current_stat_features = current_fight_stat_features(feature_columns)
    target_feature_overlap = sorted(set(feature_columns) & TARGET_COLUMNS)

    fights_date_range = date_range(fights.get("event_date", pd.Series(dtype=str)))
    summary = {
        "inputs": {
            "raw_dir": str(raw_dir),
            "training": str(training_path),
            "prefight": str(related_paths["prefight"]),
            "matchups": str(related_paths["matchups"]),
            "build_manifest": str(related_paths["manifest"]),
        },
        "row_counts": {
            "events": int(len(events)),
            "mens_fights": int(len(fights)),
            "fights": int(len(fights)),
            "fight_stats": int(len(fight_stats)),
            "fighters": int(len(fighters)),
            "prefight_snapshots": int(len(prefight)) if prefight is not None else None,
            "model_ready_matchups": int(len(matchups)) if matchups is not None else None,
            "training_rows": int(len(training)),
            "training_unique_fights": int(training["fight_id"].nunique()) if "fight_id" in training.columns else 0,
        },
        "date_range": {
            "events": date_range(events.get("event_date", pd.Series(dtype=str))),
            "fights": fights_date_range,
            "training": date_range(training.get("event_date", pd.Series(dtype=str))),
            "earliest_event_date": fights_date_range["min"],
            "latest_event_date": fights_date_range["max"],
        },
        "fights_by_year": year_counts(fights.get("event_date", pd.Series(dtype=str))),
        "fights_by_weight_class": value_counts_dict(fights.get("weight_class", pd.Series(dtype=str))),
        "profile_missingness": {
            "height": missing_summary(fighters, "height"),
            "reach": missing_summary(fighters, "reach"),
            "stance": missing_summary(fighters, "stance"),
            "date_of_birth": missing_summary(fighters, "date_of_birth"),
        },
        "outcome_checks": outcome_summary(fights, matchups, allow_mirrored),
        "duplicates": {
            "events_event_id": duplicate_id_summary(events, "event_id"),
            "fights_fight_id": duplicate_id_summary(fights, "fight_id"),
            "fight_stats_fight_fighter": duplicate_id_summary(fight_stats, ["fight_id", "fighter_id"]),
            "training_fight_id": mirrored_integrity_summary(training, allow_mirrored),
        },
        "stat_row_integrity": stat_row_integrity(fights, fight_stats),
        "weight_class_checks": {
            "womens_weight_class_rows_fights": count_contains(fights.get("weight_class", pd.Series(dtype=str)), "Women"),
            "womens_weight_class_rows_training": count_contains(
                training.get("weight_class", pd.Series(dtype=str)), "Women"
            ),
            "non_mens_bout_rows": int((fights.get("is_mens_bout", pd.Series(dtype=bool)) == False).sum())
            if "is_mens_bout" in fights.columns
            else None,
            "catchweight_or_openweight_rows": int(
                fights.get("is_catchweight_or_openweight", pd.Series(dtype=bool)).fillna(False).astype(bool).sum()
            )
            if "is_catchweight_or_openweight" in fights.columns
            else count_contains(fights.get("weight_class", pd.Series(dtype=str)), "Catch")
            + count_contains(fights.get("weight_class", pd.Series(dtype=str)), "Open"),
            "unknown_or_missing_weight_class_rows": int(
                missing_mask(fights.get("weight_class", pd.Series(dtype=str))).sum()
            ),
            "fights_by_weight_class": value_counts_dict(fights.get("weight_class", pd.Series(dtype=str))),
        },
        "target_checks": {
            "invalid_or_missing_fighter_a_won": target_invalid,
            "fighter_a_won_present": "fighter_a_won" in training.columns,
        },
        "identity_checks": {
            "same_fighter_fights": same_fighter_fights,
            "same_fighter_training_rows": same_fighter_training,
            **profile_identity_summary(fighters),
        },
        "date_checks": {
            "events": date_range(events.get("event_date", pd.Series(dtype=str))),
            "fights": fights_date_range,
            "training": date_range(training.get("event_date", pd.Series(dtype=str))),
            "prefight_history_date_violations": leakage_history,
        },
        "leakage_checks": {
            "current_fight_stat_columns_in_feature_set": current_stat_features,
            "target_columns_in_feature_set": target_feature_overlap,
            "prefight_history_date_violations": leakage_history["total"],
            "stable_fight_id_available_for_grouped_splitting": "fight_id" in training.columns
            and int(training["fight_id"].nunique()) > 0,
            "post_fight_metadata_columns_present_but_not_features": sorted(
                set(training.columns) & {"fighter_a_result", "fighter_b_result", "method", "round", "time"}
            ),
            "passed": not current_stat_features
            and not target_feature_overlap
            and leakage_history["total"] == 0
            and "fight_id" in training.columns,
        },
        "parser_warnings_or_ingest_issues": ingest_issue_summary(ingest_manifest),
        "build_manifest": build_manifest,
        "feature_completeness": {
            "feature_count": int(len(feature_completeness)),
            "usable_yes": int((feature_completeness["usable_for_sprint3_modeling"] == "yes").sum())
            if not feature_completeness.empty
            else 0,
            "usable_review": int((feature_completeness["usable_for_sprint3_modeling"] == "review").sum())
            if not feature_completeness.empty
            else 0,
            "usable_no": int((feature_completeness["usable_for_sprint3_modeling"] == "no").sum())
            if not feature_completeness.empty
            else 0,
            "highest_missing_features": feature_completeness.sort_values(
                ["missing_percentage", "missing_count"], ascending=False
            )
            .head(20)
            .to_dict("records")
            if not feature_completeness.empty
            else [],
            "zero_heavy_features": feature_completeness[
                feature_completeness["zero_percentage"] >= 90.0
            ]
            .sort_values(["zero_percentage", "zero_count"], ascending=False)
            .head(20)
            .to_dict("records")
            if not feature_completeness.empty
            else [],
        },
    }
    return summary, feature_completeness


def main() -> None:
    args = parse_args()
    out_path = Path(args.out)
    summary, feature_completeness = validate(Path(args.raw_dir), Path(args.training), args.allow_mirrored)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    feature_path = out_path.parent / "mens_feature_completeness.csv"
    feature_completeness.to_csv(feature_path, index=False, encoding="utf-8-sig")
    summary["feature_completeness"]["output_path"] = str(feature_path)
    summary = json_ready(summary)
    out_path.write_text(json.dumps(summary, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps(summary, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
