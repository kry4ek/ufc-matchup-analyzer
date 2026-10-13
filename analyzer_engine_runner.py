"""Hidden child process: prepare once, publish comparison, then predict."""
from __future__ import annotations
import importlib.util
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from analyzer_protocol import emit, progress, TIMINGS
from analyzer_support import atomic_json

def computation_cache(sex):
    from analyzer_cache import ComputeCache
    record = os.environ.get('UFC_COMPUTE_CONTEXT')
    if not record: return None
    config = json.loads(Path(record).read_text(encoding='utf-8'))
    return ComputeCache(ROOT, config['context'], enabled=config['read'])

def main():
    sex = sys.argv[1]
    comparison_only = sys.argv[2] == 'compare'
    sys.argv = [sys.argv[0]] + sys.argv[3:]
    started = time.monotonic()
    cache = computation_cache(sex)
    if sex == 'men':
        sys.path.insert(0, str(ROOT / 'mens_ufc_model'))
        from src.prediction import prediction_engine as engine
        from src.prediction.predict_matchup import parse_args, _profile_from_args
        args = parse_args()
        if cache:
            cache.wrap(engine, 'load_prediction_resources')
            cache.wrap(engine, 'train_prediction_model')
            from src.features import mens_live_v3_bayes_features as live
            from src.features import mens_live_v2_features as v2
            base_state = live._base_state_before
            v2_state = v2._state_before
            def prepared_base(context, date):
                if getattr(context, '_prepared_cutoff', None) == str(date)[:10]: return context.histories
                result = base_state(context, date)
                context._prepared_cutoff = str(date)[:10]
                return result
            def prepared_v2(context, date):
                if getattr(context, '_prepared_cutoff', None) == str(date)[:10]:
                    return context.histories, context.global_totals, context.division_totals
                result = v2_state(context, date)
                context._prepared_cutoff = str(date)[:10]
                return result
            live._base_state_before = prepared_base
            v2._state_before = prepared_v2
            original = live.prepare_live_v3_bayes_context
            def dated_context(*a, **kw):
                def compute():
                    context = original(*a, **kw)
                    live._base_state_before(context.base_context, args.fight_date)
                    v2._state_before(context.v2_context, args.fight_date)
                    return context
                return cache.get('dated_bayesian_history', {}, compute)
            live.prepare_live_v3_bayes_context = dated_context
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
        sys.modules[spec.name] = engine
        spec.loader.exec_module(engine)
        args = engine.parse_args()
        args.comparison_only = comparison_only
        if cache:
            cache.wrap(engine, 'build_elo_history_until')
            import compute_live_bayes_smoothing_features_v1 as bayes
            cache.wrap(bayes, 'load_stats')
            cache.wrap(bayes, 'compute_priors', {'division': args.division})
        prepared = engine.prepare_matchup(args)
        if cache and not comparison_only:
            prepared['cached_models'] = cache.load('fitted_womens_ensemble', {})
        output = args.json_out
    comparison = engine.comparison_from_prepared(prepared)
    from analyzer_visuals import build_visual_evidence,engine_trends
    comparison['visual_evidence']=build_visual_evidence(comparison,engine_trends(sex,prepared,comparison))
    comparison['time_to_comparison_seconds'] = round(time.monotonic() - started, 3)
    emit('comparison_ready', payload=comparison)
    if comparison_only:
        payload = comparison
    else:
        payload = engine.predict_prepared_matchup(prepared)
        payload['visual_evidence']=comparison['visual_evidence']
        if cache and sex == 'women' and not prepared.get('cached_models'):
            cache.save('fitted_womens_ensemble', {}, prepared['fitted_models'])
        payload['time_to_comparison_seconds'] = comparison['time_to_comparison_seconds']
    progress('report', 'Preparing the complete report')
    payload['stage_timings_seconds'] = {k: round(v, 3) for k, v in TIMINGS.items()}
    if cache:
        payload['compute_cache_hits'] = cache.hits
        payload['computation_timings_seconds'] = {k:round(v,3) for k,v in cache.timings.items()}
    atomic_json(Path(output), payload)

if __name__ == '__main__':
    main()
