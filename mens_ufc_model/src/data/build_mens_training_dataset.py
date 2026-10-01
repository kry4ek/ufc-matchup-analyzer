from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.features.mens_features import build_training_dataset


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build leakage-safe men's UFC training rows from normalized UFCStats tables."
    )
    parser.add_argument("--raw-dir", default="data/raw/ufcstats_men", help="Folder with events/fights/fight_stats/fighters CSVs.")
    parser.add_argument("--out", default="data/processed/mens_training_rows.csv", help="Training rows CSV path.")
    parser.add_argument(
        "--prefight-out",
        default="data/interim/mens_prefight_snapshots.csv",
        help="Pre-fight fighter snapshots CSV path.",
    )
    parser.add_argument(
        "--matchups-out",
        default="data/interim/mens_model_ready_matchups.csv",
        help="One-row-per-fight model-ready matchup CSV path.",
    )
    parser.add_argument(
        "--no-mirror",
        action="store_true",
        help="Write one canonical row per fight instead of two mirrored rows.",
    )
    parser.add_argument(
        "--keep-invalid-targets",
        action="store_true",
        help="Keep draws/no-contests with missing fighter_a_won target.",
    )
    return parser.parse_args()


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(path)
    return pd.read_csv(path)


def save_csv(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, encoding="utf-8-sig")


def main() -> None:
    args = parse_args()
    raw_dir = Path(args.raw_dir)
    fights = read_csv(raw_dir / "fights.csv")
    fight_stats = read_csv(raw_dir / "fight_stats.csv")
    fighters = read_csv(raw_dir / "fighters.csv")

    prefight, matchups, training = build_training_dataset(
        fights_df=fights,
        fight_stats_df=fight_stats,
        fighters_df=fighters,
        mirrored=not args.no_mirror,
        drop_invalid_targets=not args.keep_invalid_targets,
    )

    save_csv(prefight, Path(args.prefight_out))
    save_csv(matchups, Path(args.matchups_out))
    save_csv(training, Path(args.out))

    summary = {
        "raw_dir": str(raw_dir),
        "prefight_rows": int(len(prefight)),
        "model_ready_matchup_rows": int(len(matchups)),
        "training_rows": int(len(training)),
        "unique_training_fights": int(training["fight_id"].nunique()) if "fight_id" in training else 0,
        "mirrored": not args.no_mirror,
        "invalid_targets_kept": bool(args.keep_invalid_targets),
        "output": str(Path(args.out)),
        "prefight_output": str(Path(args.prefight_out)),
        "matchups_output": str(Path(args.matchups_out)),
    }
    manifest_path = Path(args.out).with_suffix(".manifest.json")
    manifest_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
