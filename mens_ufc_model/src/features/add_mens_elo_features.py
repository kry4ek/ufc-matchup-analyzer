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

from src.features.mens_elo import EloConfig, build_mens_elo_features


SNAPSHOT_FEATURES = [
    "elo_before",
    "division_elo_before",
    "elo_recent_trend",
    "days_since_elo_update",
    "avg_opponent_elo_before",
]

MANDATORY_ELO_COLUMNS = [
    "fighter_a_elo_before",
    "fighter_b_elo_before",
    "elo_diff",
    "fighter_a_division_elo_before",
    "fighter_b_division_elo_before",
    "division_elo_diff",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Append leakage-safe men's Elo features to mirrored training rows."
    )
    parser.add_argument("--training", default="data/processed/mens_training_rows.csv")
    parser.add_argument("--fights", default="data/raw/ufcstats_men/fights.csv")
    parser.add_argument("--out", default="data/processed/mens_training_rows_with_elo.csv")
    parser.add_argument("--audit-out", default="data/processed/mens_elo_feature_audit.json")
    parser.add_argument("--starting-elo", type=float, default=1500.0)
    parser.add_argument("--k-factor", type=float, default=32.0)
    parser.add_argument("--trend-fights", type=int, default=3)
    parser.add_argument("--opponent-summary-fights", type=int, default=5)
    return parser.parse_args()


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(path)
    return pd.read_csv(path)


def _prefixed_snapshots(snapshots: pd.DataFrame, side: str) -> pd.DataFrame:
    id_col = f"fighter_{side}_id"
    keep = ["fight_id", "fighter_id", *SNAPSHOT_FEATURES]
    out = snapshots[keep].copy()
    out = out.rename(
        columns={
            "fighter_id": id_col,
            "elo_before": f"fighter_{side}_elo_before",
            "division_elo_before": f"fighter_{side}_division_elo_before",
            "elo_recent_trend": f"fighter_{side}_elo_recent_trend",
            "days_since_elo_update": f"fighter_{side}_days_since_elo_update",
            "avg_opponent_elo_before": f"fighter_{side}_avg_opponent_elo_before",
        }
    )
    return out


def append_elo_features(training: pd.DataFrame, snapshots: pd.DataFrame) -> pd.DataFrame:
    required = {"fight_id", "fighter_a_id", "fighter_b_id"}
    missing = sorted(required - set(training.columns))
    if missing:
        raise ValueError(f"Missing required training columns: {missing}")

    out = training.copy()
    a_snapshots = _prefixed_snapshots(snapshots, "a")
    b_snapshots = _prefixed_snapshots(snapshots, "b")

    out = out.merge(a_snapshots, on=["fight_id", "fighter_a_id"], how="left", validate="many_to_one")
    out = out.merge(b_snapshots, on=["fight_id", "fighter_b_id"], how="left", validate="many_to_one")

    out["elo_diff"] = out["fighter_a_elo_before"] - out["fighter_b_elo_before"]
    out["division_elo_diff"] = (
        out["fighter_a_division_elo_before"] - out["fighter_b_division_elo_before"]
    )
    out["elo_recent_trend_diff"] = (
        out["fighter_a_elo_recent_trend"] - out["fighter_b_elo_recent_trend"]
    )
    out["days_since_elo_update_diff"] = (
        out["fighter_a_days_since_elo_update"] - out["fighter_b_days_since_elo_update"]
    )
    out["avg_opponent_elo_diff"] = (
        out["fighter_a_avg_opponent_elo_before"] - out["fighter_b_avg_opponent_elo_before"]
    )
    return out


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


def _stats_for_columns(df: pd.DataFrame, columns: list[str]) -> dict[str, dict[str, float | int | None]]:
    stats: dict[str, dict[str, float | int | None]] = {}
    for column in columns:
        if column not in df.columns:
            continue
        values = pd.to_numeric(df[column], errors="coerce")
        stats[column] = {
            "missing": int(values.isna().sum()),
            "min": None if values.dropna().empty else float(values.min()),
            "max": None if values.dropna().empty else float(values.max()),
            "mean": None if values.dropna().empty else float(values.mean()),
        }
    return stats


def _combined_rating_stats(df: pd.DataFrame, columns: list[str]) -> dict[str, float | int | None]:
    values = pd.concat([pd.to_numeric(df[col], errors="coerce") for col in columns if col in df], axis=0)
    values = values.dropna()
    if values.empty:
        return {"count": 0, "min": None, "max": None, "mean": None}
    return {
        "count": int(len(values)),
        "min": float(values.min()),
        "max": float(values.max()),
        "mean": float(values.mean()),
    }


def _mirrored_sign_check(df: pd.DataFrame, diff_col: str) -> dict[str, Any]:
    if "fight_id" not in df.columns or diff_col not in df.columns:
        return {"passed": False, "reason": "missing_required_columns"}

    checked = 0
    violations: list[dict[str, Any]] = []
    for fight_id, group in df.groupby("fight_id", sort=False):
        values = pd.to_numeric(group[diff_col], errors="coerce").dropna().tolist()
        if len(values) != 2:
            violations.append(
                {"fight_id": fight_id, "reason": "expected_two_non_missing_values", "count": len(values)}
            )
            continue
        checked += 1
        if abs(values[0] + values[1]) > 1e-8:
            violations.append({"fight_id": fight_id, "sum": values[0] + values[1]})

    return {
        "passed": len(violations) == 0,
        "checked_pairs": int(checked),
        "violation_count": int(len(violations)),
        "violations_sample": violations[:20],
    }


def build_audit(training: pd.DataFrame, output: pd.DataFrame, elo_audit: dict[str, Any]) -> dict[str, Any]:
    elo_cols = [col for col in output.columns if "elo" in col.lower()]
    mandatory_missing = {col: int(output[col].isna().sum()) for col in MANDATORY_ELO_COLUMNS}
    all_elo_missing = {col: int(output[col].isna().sum()) for col in elo_cols}

    return {
        "input_rows": int(len(training)),
        "output_rows": int(len(output)),
        "unique_training_fights": int(output["fight_id"].nunique()) if "fight_id" in output else 0,
        "row_directions": output["row_direction"].value_counts(dropna=False).to_dict()
        if "row_direction" in output
        else {},
        "mandatory_elo_missing": mandatory_missing,
        "all_elo_missing": all_elo_missing,
        "elo_column_stats": _stats_for_columns(output, elo_cols),
        "overall_elo_rating_stats": _combined_rating_stats(
            output, ["fighter_a_elo_before", "fighter_b_elo_before"]
        ),
        "division_elo_rating_stats": _combined_rating_stats(
            output, ["fighter_a_division_elo_before", "fighter_b_division_elo_before"]
        ),
        "mirrored_sign_checks": {
            "elo_diff": _mirrored_sign_check(output, "elo_diff"),
            "division_elo_diff": _mirrored_sign_check(output, "division_elo_diff"),
        },
        "elo_engine_audit": elo_audit,
    }


def main() -> None:
    args = parse_args()
    config = EloConfig(
        starting_elo=args.starting_elo,
        k_factor=args.k_factor,
        trend_fights=args.trend_fights,
        opponent_summary_fights=args.opponent_summary_fights,
    )

    training = read_csv(Path(args.training))
    fights = read_csv(Path(args.fights))
    snapshots, elo_audit = build_mens_elo_features(fights, config=config)
    output = append_elo_features(training, snapshots)
    audit = build_audit(training, output, elo_audit)

    out_path = Path(args.out)
    audit_path = Path(args.audit_out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    output.to_csv(out_path, index=False, encoding="utf-8-sig")
    audit_path.write_text(json.dumps(audit, indent=2, default=_json_default), encoding="utf-8")

    print(json.dumps(audit, indent=2, default=_json_default))


if __name__ == "__main__":
    main()
