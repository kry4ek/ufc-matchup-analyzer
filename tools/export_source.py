"""Explicit, repeatable export of the retained research engine files."""
from pathlib import Path
import argparse, csv, hashlib, json, shutil, subprocess
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

FILES = '''
mens_ufc_model/src/common/utils.py
mens_ufc_model/src/data/build_mens_training_dataset.py
mens_ufc_model/src/data/ingest_ufcstats.py
mens_ufc_model/src/data/ufcstats_scraper.py
mens_ufc_model/src/features/add_mens_elo_features.py
mens_ufc_model/src/features/build_mens_advanced_features.py
mens_ufc_model/src/features/build_mens_bayes_smoothing_candidate.py
mens_ufc_model/src/features/mens_elo.py
mens_ufc_model/src/features/mens_features.py
mens_ufc_model/src/features/mens_live_v2_features.py
mens_ufc_model/src/features/mens_live_v3_bayes_features.py
mens_ufc_model/src/models/model_registry.py
mens_ufc_model/src/models/train_baseline.py
mens_ufc_model/src/prediction/fighter_lookup.py
mens_ufc_model/src/prediction/predict_matchup.py
mens_ufc_model/src/prediction/prediction_engine.py
mens_ufc_model/src/validation/validate_mens_dataset.py
mens_ufc_model/src/validation/validate_live_v3_bayes_parity.py
mens_ufc_model/update_ufc_mens_dataset_incremental.py
womens_ufc_model/predict_matchup_advanced.py
womens_ufc_model/compute_live_bayes_smoothing_features_v1.py
womens_ufc_model/update_ufc_womens_dataset_incremental.py
womens_ufc_model/build_prefight_bayesian_smoothing_v1_REBUILT.py
'''.split()
DATA = '''
mens_ufc_model/data/raw/ufcstats_men/events.csv
mens_ufc_model/data/raw/ufcstats_men/fights.csv
mens_ufc_model/data/raw/ufcstats_men/fight_stats.csv
mens_ufc_model/data/raw/ufcstats_men/fighters.csv
mens_ufc_model/data/interim/mens_prefight_snapshots.csv
mens_ufc_model/data/interim/mens_model_ready_matchups.csv
mens_ufc_model/data/processed/mens_training_rows.csv
mens_ufc_model/data/processed/mens_training_rows_with_elo.csv
mens_ufc_model/data/processed/mens_training_rows_v2_advanced.csv
mens_ufc_model/data/processed/mens_training_rows_v3_bayes_smoothing_candidate.csv
womens_ufc_model/output_td_repaired/ufc_womens_fighter_fight_stats_td_control_repaired.csv
womens_ufc_model/output_advanced_features_sig_fixed/ufc_womens_model_training_rows_advanced_sig_fixed.csv
womens_ufc_model/output_bayesian_prefight_smoothing_sig_fixed_v1/ufc_womens_model_training_rows_advanced_plus_bayes_prefight_smoothing_v1.csv
womens_ufc_model/output_advanced_features/advanced_prefight_snapshots.csv
womens_ufc_model/output_quality_fixed/ufc_womens_fighter_profiles.csv
'''.split()

EVENT_SELECTION = '''def select_completed_events(events, cutoff, today, max_events=None):
    """Exclude future listings before imposing the bounded inspection limit."""
    selected = [event for event in events if cutoff <= pd.Timestamp(event["event_date"]).normalize() <= today]
    return selected[:max_events] if max_events is not None else selected


'''

def sha(path):
    return hashlib.file_digest(path.open('rb'), 'sha256').hexdigest()

MEN_REPORT_ADDITION = '''        # Report the already computed live values, without changing model inputs.
        # Keep the legacy snapshots intact for existing JSON consumers.
        "fighter_a_comparison": _jsonable({
            **snapshot_a,
            **comparison_a,
            **elo_a,
            **{k[len("fighter_a_"):]: v for k, v in forward_row.items() if k.startswith("fighter_a_")},
        }),
        "fighter_b_comparison": _jsonable({
            **snapshot_b,
            **comparison_b,
            **elo_b,
            **{k[len("fighter_b_"):]: v for k, v in forward_row.items() if k.startswith("fighter_b_")},
        }),
'''

MEN_V2_REPORT_HELPER = '''def _report_snapshot(snapshot: dict[str, Any], history: dict[str, Any]) -> dict[str, Any]:
    """Copy dated values and existing method counters for reporting only."""
    return {
        **snapshot,
        "finish_wins_before": int(history["finish_wins"]),
        "ko_tko_wins_before": int(history["ko_tko_wins"]),
        "submission_wins_before": int(history["sub_wins"]),
        "decision_wins_before": int(history["decision_wins"]),
        "finish_losses_before": int(history["finish_losses"]),
    }


'''

WOMEN_REPORT_ADDITION = '''
    # These are the same live values, weights, and checks used above; reporting
    # exposes them without recomputing features or changing the ensemble.
    for side, snapshot in (("a", snapshot_a), ("b", snapshot_b)):
        prefix = f"fighter_{side}_"
        live_values = {
            str(column)[len(prefix):]: value
            for column, value in pred_row_forward.iloc[0].items()
            if str(column).startswith(prefix)
        }
        summary[f"fighter_{side}_comparison"] = {**snapshot, **live_values}
    summary["model_weights"] = dict(ensemble_weights)
    summary["model_predictions"] = pred_df.to_dict(orient="records") + [dict(ensemble_row)]
    summary["reliability_factors"] = list(reliability.get("factors", []))
    summary["reliability_notes"] = list(reliability.get("notes", []))
'''

def replace_once(text, old, new, description):
    if text.count(old) != 1:
        raise ValueError('Expected reporting location was not found exactly once: '+description)
    return text.replace(old, new, 1)

def adapt_prediction_reports(rel, text):
    """Expose computed report details; preserve all prediction calculations."""
    if rel == 'mens_ufc_model/src/prediction/prediction_engine.py':
        marker='    warnings = warnings or []\n    forward_row = build_matchup_row(\n'
        new='    warnings = warnings or []\n    comparison_a: dict[str, Any] = {}\n    comparison_b: dict[str, Any] = {}\n    forward_row = build_matchup_row(\n'
        text=replace_once(text, marker, new, 'men report snapshot locals')
        for version in ('v2', 'v3'):
            marker=f'        warnings.extend({version}_rows.warnings)\n'
            new=marker+f'        comparison_a = getattr({version}_rows, "fighter_a_comparison", {{}})\n        comparison_b = getattr({version}_rows, "fighter_b_comparison", {{}})\n'
            text=replace_once(text, marker, new, 'men '+version+' report snapshots')
        marker='        "feature_summary": {\n'
        return replace_once(text, marker, MEN_REPORT_ADDITION+marker, 'men comparison payload')
    if rel == 'mens_ufc_model/src/features/mens_live_v2_features.py':
        marker='class LiveV2FeatureRows:\n    forward: dict[str, Any]\n    reverse: dict[str, Any]\n    warnings: list[str]\n'
        new=marker+'    fighter_a_comparison: dict[str, Any] = field(default_factory=dict)\n    fighter_b_comparison: dict[str, Any] = field(default_factory=dict)\n'
        text=replace_once(text, marker, new, 'v2 report dataclass fields')
        marker='def _warning_label(label: str, fighter: Any) -> str:\n'
        text=replace_once(text, marker, MEN_V2_REPORT_HELPER+marker, 'v2 report snapshot helper')
        old='    return LiveV2FeatureRows(forward=forward, reverse=reverse, warnings=warnings)\n'
        new='''    return LiveV2FeatureRows(
        forward=forward,
        reverse=reverse,
        warnings=warnings,
        fighter_a_comparison=_report_snapshot(snapshot_a, histories[fighter_a.fighter_id]),
        fighter_b_comparison=_report_snapshot(snapshot_b, histories[fighter_b.fighter_id]),
    )
'''
        return replace_once(text, old, new, 'v2 report snapshots return')
    if rel == 'mens_ufc_model/src/features/mens_live_v3_bayes_features.py':
        marker='class LiveV3BayesFeatureRows:\n    forward: dict[str, Any]\n    reverse: dict[str, Any]\n    warnings: list[str]\n    leakage_audit: dict[str, Any]\n'
        new=marker+'    fighter_a_comparison: dict[str, Any] = field(default_factory=dict)\n    fighter_b_comparison: dict[str, Any] = field(default_factory=dict)\n'
        text=replace_once(text, marker, new, 'v3 report dataclass fields')
        old='        warnings=warnings,\n        leakage_audit=leakage_audit,\n    )\n'
        new='        warnings=warnings,\n        leakage_audit=leakage_audit,\n        fighter_a_comparison=dict(v2_rows.fighter_a_comparison),\n        fighter_b_comparison=dict(v2_rows.fighter_b_comparison),\n    )\n'
        return replace_once(text, old, new, 'v3 forward dated report snapshots')
    if rel == 'womens_ufc_model/predict_matchup_advanced.py':
        marker='def json_safe_value(value):\n'
        nested='''    if isinstance(value, dict):
        return {str(key): json_safe_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe_value(item) for item in value]
'''
        text=replace_once(text, marker, marker+nested, 'women nested JSON serializer')
        old='    market_comparison,\n    market_edge,\n):\n'
        new='    market_comparison,\n    market_edge,\n    ensemble_weights,\n    pred_row_forward,\n):\n'
        text=replace_once(text, old, new, 'women report function inputs')
        marker='\n    for model_name, row in model_rows.items():\n'
        text=replace_once(text, marker, WOMEN_REPORT_ADDITION+marker, 'women comparison payload')
        old='            market_comparison=market_comparison,\n            market_edge=market_edge,\n        )\n'
        new='            market_comparison=market_comparison,\n            market_edge=market_edge,\n            ensemble_weights=ensemble_weights,\n            pred_row_forward=pred_row_forward,\n        )\n'
        text=replace_once(text, old, new, 'women report function call')
        marker='        summary["manual_profile_fallback_used"] = bool(manual_profile_fallback_fighters)\n'
        history='''        for side, fighter in (("a", fighter_a), ("b", fighter_b)):
            history_dates = hist_stats.loc[hist_stats["fighter"] == fighter, "event_date"].dropna()
            summary[f"fighter_{side}_comparison"]["history_max_event_date_before"] = (
                pd.Timestamp(history_dates.max()).strftime("%Y-%m-%d") if not history_dates.empty else None
            )
'''
        return replace_once(text, marker, history+marker, 'women cutoff-filtered history date')
    return text

def main():
    p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True);p.add_argument('--destination',type=Path,required=True)
    a=p.parse_args();a.destination.mkdir(parents=True,exist_ok=True)
    inits=list(a.source.joinpath('mens_ufc_model/src').rglob('__init__.py'))
    files=sorted(set(FILES+[x.relative_to(a.source).as_posix() for x in inits if any(rel.startswith(x.parent.relative_to(a.source).as_posix()+'/') for rel in FILES)]))
    records=[]
    for rel in files+DATA:
        src=a.source/rel;dest=a.destination/rel;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(src,dest)
        if rel in files:dest.write_text(src.read_text(encoding='utf-8'),encoding='utf-8',newline='\n')
        if rel.endswith('model_registry.py'):
            dest.write_text(dest.read_text(encoding='utf-8').replace('DEFAULT_MODEL_VERSION = "v1_baseline"','DEFAULT_MODEL_VERSION = "v3_bayes_smoothed"'),encoding='utf-8',newline='\n')
        if rel.endswith('build_mens_bayes_smoothing_candidate.py'):
            text=dest.read_text(encoding='utf-8');start=text.index('DEFAULT_MANIFEST_OUT = (');end=text.index('\n\nTARGET_OR_POSTFIGHT',start)
            dest.write_text(text[:start]+'DEFAULT_MANIFEST_OUT = Path("_update_manifests/feature_columns.csv")'+text[end:],encoding='utf-8',newline='\n')
        if rel=='womens_ufc_model/predict_matchup_advanced.py':
            text=dest.read_text(encoding='utf-8')
            old='        except Exception:\n            weights[name] = 1.0'
            new='        except Exception as exc:\n            # A failed worker must not silently change the selected ensemble.\n            # Successful calculations and the legitimate low-row fallback above\n            # are unchanged; public callers can diagnose/retry this failure.\n            raise RuntimeError("Model weight cross-validation failed; prediction stopped instead of using fallback weights.") from exc'
            if text.count(old)!=1:raise ValueError('Expected women ensemble fallback was not found exactly once')
            dest.write_text(text.replace(old,new),encoding='utf-8',newline='\n')
        if rel in ('mens_ufc_model/src/prediction/prediction_engine.py', 'mens_ufc_model/src/features/mens_live_v2_features.py', 'mens_ufc_model/src/features/mens_live_v3_bayes_features.py', 'womens_ufc_model/predict_matchup_advanced.py'):
            dest.write_text(adapt_prediction_reports(rel,dest.read_text(encoding='utf-8')),encoding='utf-8',newline='\n')
        if rel.endswith('dataset_incremental.py'):
            text=dest.read_text(encoding='utf-8')
            marker='    events = parse_event_list(events_soup)'
            if marker not in text:raise ValueError('Expected updater event-list guard location was not found: '+rel)
            text=text.replace(marker,marker+'\n    if not events:\n        raise ValueError("UFCStats returned no parseable completed events; refusing an apparent empty update.")')
            text=text.replace('def parse_event_list(',EVENT_SELECTION+'def parse_event_list(',1)
            variable='event' if rel.startswith('mens_') else 'e'
            condition='is not None' if rel.startswith('mens_') else ''
            old=f'    new_events = [{variable} for {variable} in events if pd.Timestamp({variable}["event_date"]).normalize() >= cutoff]\n    if args.max_events'+(' is not None' if condition else '')+':\n        new_events = new_events[: args.max_events]'
            start=text.rfind(old)
            if start<0:raise ValueError('Expected safe updater selection was not found: '+rel)
            text=text[:start]+'    new_events = select_completed_events(events, cutoff, today, args.max_events)'+text[start+len(old):]
            dest.write_text(text,encoding='utf-8',newline='\n')
        if rel in ('mens_ufc_model/src/prediction/prediction_engine.py','womens_ufc_model/predict_matchup_advanced.py'):
            from tools.adapt_workflows import adapt_men,adapt_women
            adapter=adapt_men if rel.startswith('mens_') else adapt_women
            dest.write_text(adapter(dest.read_text(encoding='utf-8')),encoding='utf-8',newline='\n')
        if rel in files:records.append(dict(path=rel,source_sha256=sha(src),exported_sha256=sha(dest)))
    provenance=dict(source_commit=subprocess.check_output(['git','-C',str(a.source),'rev-parse','HEAD'],text=True).strip(),allowlist=files,files=records,adaptations=['public men default v3','feature manifest relocated','updaters reject empty or malformed event listings','updaters filter future events before applying inspection limits','women cross-validation failures stop prediction instead of silently changing ensemble weights','prediction JSON exposes computed live comparison values, women ensemble weights and full reliability details without changing calculations','UTF-8 and LF line endings for portable checkout hashes'])
    provenance['adaptations'].append('v0.3 prepares dated comparison once before unchanged prediction fitting and exposes structured progress')
    (a.destination/'source_manifest.json').write_text(json.dumps(provenance,indent=2)+'\n',encoding='utf-8',newline='\n')
    dataset=[]
    for rel in DATA:
        f=a.destination/rel
        with f.open(encoding='utf-8-sig',newline='') as h:
            reader=csv.DictReader(h);schema=reader.fieldnames;count=0;latest=''
            for row in reader:
                count+=1;d=row.get('event_date',row.get('date','')) or ''
                if d>latest:latest=d
        dataset.append(dict(path=rel,sha256=sha(f),size_bytes=f.stat().st_size,rows=count,columns=schema,latest_date=latest or None))
    manifest=dict(version='0.3.0',source='UFCStats; derived features from retained engines',redistribution_status='review_required',release_repository=None,files=dataset)
    (a.destination/'dataset_manifest.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8',newline='\n')
    print(f'Exported {len(files)} source files and {len(DATA)} datasets; {sum(x["size_bytes"] for x in dataset)/1048576:.1f} MiB data')

if __name__=='__main__':main()
