"""Hidden child process: prepare once, publish comparison, then predict."""
from __future__ import annotations
import importlib.util
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from analyzer_protocol import emit, progress, TIMINGS
from analyzer_support import atomic_json

def main():
    sex = sys.argv[1]
    comparison_only = sys.argv[2] == 'compare'
    sys.argv = [sys.argv[0]] + sys.argv[3:]
    started = time.monotonic()
    if sex == 'men':
        sys.path.insert(0, str(ROOT / 'mens_ufc_model'))
        from src.prediction import prediction_engine as engine
        from src.prediction.predict_matchup import parse_args, _profile_from_args
        args = parse_args()
        prepared = engine.prepare_matchup(
            fighter_a=args.fighter_a, fighter_b=args.fighter_b, fight_date=args.fight_date,
            fighter_a_id=args.fighter_a_id, fighter_b_id=args.fighter_b_id,
            fighter_a_profile=_profile_from_args(args, 'fighter-a'), fighter_b_profile=_profile_from_args(args, 'fighter-b'),
            weight_class=args.weight_class, training_path=args.training, raw_dir=args.raw_dir,
            model_name=args.model, model_version=args.model_version, shrink_factor=args.shrink_factor,
            no_shrink=args.no_shrink, as_of_date=args.as_of_date, allow_future_training_rows=args.allow_future_training_rows)
        output = args.out
    else:
        sys.path.insert(0, str(ROOT / 'womens_ufc_model'))
        spec = importlib.util.spec_from_file_location('women_engine', ROOT / 'womens_ufc_model/predict_matchup_advanced.py')
        engine = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(engine)
        args = engine.parse_args()
        args.comparison_only = comparison_only
        prepared = engine.prepare_matchup(args)
        output = args.json_out
    comparison = engine.comparison_from_prepared(prepared)
    comparison['time_to_comparison_seconds'] = round(time.monotonic() - started, 3)
    emit('comparison_ready', payload=comparison)
    if comparison_only:
        payload = comparison
    else:
        payload = engine.predict_prepared_matchup(prepared)
        payload['time_to_comparison_seconds'] = comparison['time_to_comparison_seconds']
    progress('report', 'Preparing the complete report')
    payload['stage_timings_seconds'] = {k: round(v, 3) for k, v in TIMINGS.items()}
    atomic_json(Path(output), payload)

if __name__ == '__main__':
    main()
