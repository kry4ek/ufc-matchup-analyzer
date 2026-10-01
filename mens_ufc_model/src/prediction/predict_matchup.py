from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from src.prediction.prediction_engine import (  # noqa: E402
    DEFAULT_RAW_DIR,
    DEFAULT_TRAINING,
    dump_prediction_json,
    predict_single_matchup,
)
from src.models.model_registry import DEFAULT_MODEL_VERSION, supported_model_versions  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Predict an independent men's UFC matchup with a registered men model version."
    )
    parser.add_argument("--fighter-a", required=True, help="First men's fighter name.")
    parser.add_argument("--fighter-b", required=True, help="Second men's fighter name.")
    parser.add_argument("--fighter-a-id", default=None, help="Optional UFCStats fighter ID for fighter A.")
    parser.add_argument("--fighter-b-id", default=None, help="Optional UFCStats fighter ID for fighter B.")
    parser.add_argument("--fighter-a-height-cm", default="", help="Optional manual profile height for fighter A.")
    parser.add_argument("--fighter-a-reach-cm", default="", help="Optional manual profile reach for fighter A.")
    parser.add_argument("--fighter-a-stance", default="", help="Optional manual profile stance for fighter A.")
    parser.add_argument("--fighter-a-date-of-birth", default="", help="Optional manual profile DOB for fighter A.")
    parser.add_argument("--fighter-b-height-cm", default="", help="Optional manual profile height for fighter B.")
    parser.add_argument("--fighter-b-reach-cm", default="", help="Optional manual profile reach for fighter B.")
    parser.add_argument("--fighter-b-stance", default="", help="Optional manual profile stance for fighter B.")
    parser.add_argument("--fighter-b-date-of-birth", default="", help="Optional manual profile DOB for fighter B.")
    parser.add_argument("--fight-date", required=True, help="Prediction fight date, YYYY-MM-DD.")
    parser.add_argument(
        "--as-of-date",
        default=None,
        help=(
            "Training cutoff date, YYYY-MM-DD. Defaults to today for live/future fights; "
            "historical fights default to the day before fight-date."
        ),
    )
    parser.add_argument(
        "--allow-future-training-rows",
        action="store_true",
        help=(
            "Allow the source training CSV to contain rows after --as-of-date. "
            "Rows after as-of are still excluded from model training."
        ),
    )
    parser.add_argument("--weight-class", default=None, help="Optional UFC weight class context.")
    parser.add_argument(
        "--model-version",
        default=DEFAULT_MODEL_VERSION,
        choices=supported_model_versions(),
        help="Registered men model version to use.",
    )
    parser.add_argument(
        "--training",
        default=None,
        help="Training CSV. Defaults to the selected model version's registered training file.",
    )
    parser.add_argument("--raw-dir", default=DEFAULT_RAW_DIR)
    parser.add_argument(
        "--model",
        default=None,
        choices=["logistic", "ensemble"],
        help="Optional model type override; defaults to the selected model version's required model.",
    )
    parser.add_argument("--shrink-factor", type=float, default=0.90)
    parser.add_argument("--no-shrink", action="store_true")
    parser.add_argument("--out", default=None, help="Optional JSON output path.")
    parser.add_argument("--verbose", action="store_true")
    return parser.parse_args()


def _pct(value: Any) -> str:
    if value is None:
        return "n/a"
    return f"{float(value) * 100:.1f}%"


def _number(value: Any, digits: int = 1) -> str:
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return "n/a"


def _profile_from_args(args: argparse.Namespace, side: str) -> dict[str, Any] | None:
    prefix = side.replace("-", "_")
    profile = {
        "height_cm": getattr(args, f"{prefix}_height_cm"),
        "reach_cm": getattr(args, f"{prefix}_reach_cm"),
        "stance": getattr(args, f"{prefix}_stance"),
        "date_of_birth": getattr(args, f"{prefix}_date_of_birth"),
    }
    return profile if any(str(value or "").strip() for value in profile.values()) else None


def print_console(payload: dict[str, Any], *, verbose: bool) -> None:
    print("Men's UFC Matchup Prediction")
    print("=" * 31)
    print(f"Fight: {payload['fighter_a']} vs {payload['fighter_b']}")
    print(f"Fight date: {payload['fight_date']}")
    print(f"As-of date: {payload['as_of_date']} ({payload['as_of_date_source']})")
    print(f"Weight class: {payload['weight_class']}")
    print(f"Model: {payload['model']} ({payload['model_version']})")
    print(f"Feature policy: {payload['feature_policy']}")
    print(f"Logistic C: {payload['logistic_c']}")
    print(f"Training filter cutoff: {payload['training_filter_cutoff']}")
    print(f"Actual max training event_date used: {payload['actual_max_training_event_date_used']}")
    print(
        "Training rows/fights: "
        f"{payload['training_rows']} rows / {payload['training_unique_fights']} fights "
        f"({payload['training_date_min']} to {payload['training_date_max']})"
    )
    print()
    print("Probabilities")
    print(f"- {payload['fighter_a']} raw forward: {_pct(payload['fighter_a_raw_probability'])}")
    print(
        "- "
        f"{payload['fighter_a']} reverse-adjusted raw: "
        f"{_pct(payload['fighter_a_reverse_adjusted_raw_probability'])}"
    )
    print(f"- {payload['fighter_a']} raw average: {_pct(payload['fighter_a_raw_avg_probability'])}")
    print(
        f"- {payload['fighter_a']} final: {_pct(payload['fighter_a_final_probability'])} "
        f"(shrink factor {payload['shrink_factor']:.2f})"
    )
    print(f"- {payload['fighter_b']} final: {_pct(payload['fighter_b_final_probability'])}")
    print()
    print(f"Predicted winner: {payload['predicted_winner']}")
    print(f"Confidence tier: {payload['confidence_tier']}")
    print()
    print("Feature summary")
    summary = payload["feature_summary"]
    print(f"- Stance matchup: {summary['stance_matchup']}")
    print(f"- Catch/openweight flag: {summary['is_catchweight_or_openweight']}")
    print(
        "- Elo before: "
        f"{payload['fighter_a']} {_number(summary['fighter_a_elo_before'])}, "
        f"{payload['fighter_b']} {_number(summary['fighter_b_elo_before'])}"
    )
    print("Top feature differences:")
    for item in payload["top_feature_differences"][:8]:
        print(f"- {item['feature']}: {item['difference']:.4f}")
    print()
    print("Data quality warnings")
    if payload["warnings"]:
        for warning in payload["warnings"]:
            print(f"- {warning}")
    else:
        print("- None")
    if verbose:
        print()
        print("Features used")
        for feature in payload["features_used"]:
            print(f"- {feature}")


def main() -> None:
    args = parse_args()
    try:
        payload = predict_single_matchup(
            fighter_a=args.fighter_a,
            fighter_b=args.fighter_b,
            fight_date=args.fight_date,
            fighter_a_id=args.fighter_a_id,
            fighter_b_id=args.fighter_b_id,
            fighter_a_profile=_profile_from_args(args, "fighter-a"),
            fighter_b_profile=_profile_from_args(args, "fighter-b"),
            weight_class=args.weight_class,
            training_path=args.training,
            raw_dir=args.raw_dir,
            model_name=args.model,
            model_version=args.model_version,
            shrink_factor=args.shrink_factor,
            no_shrink=args.no_shrink,
            as_of_date=args.as_of_date,
            allow_future_training_rows=args.allow_future_training_rows,
        )
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc

    print_console(payload, verbose=args.verbose)
    if args.out:
        out_path = Path(args.out)
        dump_prediction_json(payload, out_path)
        print()
        print(f"Wrote JSON: {out_path}")


if __name__ == "__main__":
    main()
