"""Reproducible preparation/progress adapters over the retained 0.2.1 engines."""
from pathlib import Path
import ast
import textwrap

def names(text, context):
    return {n.id for n in ast.walk(ast.parse(textwrap.dedent(text))) if isinstance(n, ast.Name) and isinstance(n.ctx, context)}

def adapt_men(text):
    if 'def predict_prepared_matchup(' in text: return text
    text = text.replace('import sys\n', 'import sys\nfrom analyzer_protocol import progress as stage_progress\n', 1)
    start = text.index('def build_prediction_result(')
    end = text.index('\n\ndef predict_single_matchup(', start)
    old = text[start:end]
    body_start = old.index('    import numpy as np')
    split = old.index('    missing_live_features =')
    prep_body = old[body_start:split].replace('model_bundle.model_version', 'model_version')
    helper = '''def prepare_feature_rows(*, fighter_a, fighter_b, fight_date, weight_class,
                         snapshot_a, snapshot_b, elo_a, elo_b, model_version,
                         warnings=None, live_v2_context=None):
'''+prep_body+'''    return dict(forward_row=forward_row, reverse_row=reverse_row,
                comparison_a=comparison_a, comparison_b=comparison_b, warnings=warnings)


'''
    header = old[:body_start].replace('    live_v2_context: Any = None,', '    live_v2_context: Any = None,\n    prepared_features: dict[str, Any] | None = None,')
    reuse = '''    import numpy as np
    prepared_features = prepared_features or prepare_feature_rows(
        fighter_a=fighter_a, fighter_b=fighter_b, fight_date=fight_date,
        weight_class=weight_class, snapshot_a=snapshot_a, snapshot_b=snapshot_b,
        elo_a=elo_a, elo_b=elo_b, model_version=model_bundle.model_version,
        warnings=warnings, live_v2_context=live_v2_context)
    forward_row = prepared_features['forward_row']
    reverse_row = prepared_features['reverse_row']
    comparison_a = prepared_features['comparison_a']
    comparison_b = prepared_features['comparison_b']
    warnings = prepared_features['warnings']
'''
    text = text[:start]+helper+header+reuse+old[split:]+text[end:]
    start = text.index('def predict_single_matchup(')
    old = text[start:]
    body_start = old.index('    from src.prediction.fighter_lookup import')
    signature = old[:body_start].replace('    live_v2_context: Any = None,', '    live_v2_context: Any = None,\n    progress=None,')
    train_start = old.index('    if model_bundle is None:')
    context_start = old.index('    if config.model_version == "v2_smoothed_debutant" and live_v2_context is None:')
    result_start = old.index('    return serialize_prediction(', context_start)
    prelude = old[body_start:train_start]
    prelude = '    notify = progress or stage_progress\n'+prelude
    prelude = prelude.replace('    resources = resources or load_prediction_resources(', '    notify("loading", "Loading training data and fight history")\n    resources = resources or load_prediction_resources(', 1)
    prelude = prelude.replace('    snapshot_a, snapshot_b, elo_a, elo_b = build_prediction_snapshots(', '    notify("features", "Preparing dated fighter snapshots and Elo")\n    snapshot_a, snapshot_b, elo_a, elo_b = build_prediction_snapshots(', 1)
    preparation = signature.replace('def predict_single_matchup(', 'def prepare_matchup(')+prelude+old[context_start:result_start]+'''    prepared_features = prepare_feature_rows(
        fighter_a=fighter_a_result, fighter_b=fighter_b_result, fight_date=parsed_fight_date,
        weight_class=normalized_weight_class, snapshot_a=snapshot_a, snapshot_b=snapshot_b,
        elo_a=elo_a, elo_b=elo_b, model_version=config.model_version,
        warnings=warnings, live_v2_context=live_v2_context)
    return locals()


def comparison_from_prepared(prepared):
    p = prepared
    f = p['prepared_features']
    payload = dict(fighter_a=p['fighter_a_result'].fighter_name,
                   fighter_b=p['fighter_b_result'].fighter_name,
                   fight_date=_date_text(p['parsed_fight_date']), division=p['normalized_weight_class'],
                   model_version=p['config'].model_version, result_state='comparison',
                   warnings=sorted(set(f['warnings'])))
    for side in ('a', 'b'):
        snapshot = p['snapshot_'+side]
        elo = p['elo_'+side]
        advanced = f['comparison_'+side]
        prefix = 'fighter_'+side+'_'
        payload[prefix+'snapshot'] = snapshot
        payload[prefix+'comparison'] = {**snapshot, **advanced, **elo,
            **{k[len(prefix):]:v for k,v in f['forward_row'].items() if k.startswith(prefix)}}
    return serialize_prediction(payload)


def predict_prepared_matchup(prepared, progress=None):
'''
    state_names = ['parsed_fight_date','selected_model_name','config','resources','as_of_date','allow_future_training_rows','model_bundle','fighter_a_result','fighter_b_result','normalized_weight_class','snapshot_a','snapshot_b','elo_a','elo_b','shrink_factor','no_shrink','warnings','live_v2_context','prepared_features']
    bindings = ''.join(f'    {n} = prepared[{n!r}]\n' for n in state_names)
    result = old[result_start:].replace('            live_v2_context=live_v2_context,', '            live_v2_context=live_v2_context,\n            prepared_features=prepared_features,', 1)
    result = '    stage_progress("prediction", "Calculating forward/reverse probabilities and calibration")\n'+result
    prediction = '    notify = progress or stage_progress\n'+bindings+'    notify("training", "Fitting the men’s selected model")\n'+old[train_start:context_start]+result.replace('stage_progress(', 'notify(')
    wrapper = '\n\n'+signature+'    prepared = prepare_matchup(**locals())\n    return predict_prepared_matchup(prepared, progress=progress)\n'
    return text[:start]+preparation+prediction+wrapper

def adapt_women(text):
    if 'def predict_prepared_matchup(' in text: return text
    text = text.replace('def main():\n    args = parse_args()\n', 'def prepare_matchup(args, progress=None):\n', 1)
    start = text.index('def prepare_matchup(')
    boundary = text.index('    X_train = model_train_df[feature_cols]', start)
    ending = text.index('\n\nif __name__ == "__main__":', boundary)
    prelude = text[start:boundary]
    prelude = prelude.replace('def prepare_matchup(args, progress=None):\n', 'def prepare_matchup(args, progress=None):\n    notify = progress or stage_progress\n')
    prelude = prelude.replace('    train_df = pd.read_csv(train_path)', '    notify("loading", "Loading women’s training data and fight history")\n    train_df = pd.read_csv(train_path)', 1)
    prelude = prelude.replace('    hist_stats, overall_elo, division_elo = build_elo_history_until(stats, fight_date)', '    notify("features", "Preparing dated fighter snapshots, Elo and Bayesian features")\n    hist_stats, overall_elo, division_elo = build_elo_history_until(stats, fight_date)', 1)
    prelude = prelude.replace('    if model_train_df.empty:', "    if model_train_df.empty and not getattr(args, 'comparison_only', False):")
    prelude = prelude.replace('    if model_train_df["fighter_a_won"].nunique() < 2:', "    if model_train_df[\"fighter_a_won\"].nunique() < 2 and not getattr(args, 'comparison_only', False):")
    tail = text[boundary:ending]
    # The structured result is now produced even when no output file was requested.
    block_start = tail.index('    if args.json_out:\n')
    block_end = tail.index('    print_market_comparison(', block_start)
    block = tail[block_start:block_end]
    lines = block.splitlines(True)[1:]
    lines = [line[4:] if line.startswith('    ') else line for line in lines]
    unindented = ''.join(lines)
    unindented = unindented.replace('    json_out_path = Path(args.json_out)\n    json_out_path.parent.mkdir(parents=True, exist_ok=True)\n', '')
    write_start = unindented.index('    json_out_path.write_text(')
    write_end = unindented.index('\n\n', write_start)
    write = unindented[write_start:write_end]
    unindented = unindented[:write_start]+'    if args.json_out:\n        json_out_path = Path(args.json_out)\n        json_out_path.parent.mkdir(parents=True, exist_ok=True)\n'+textwrap.indent(write, '    ')+unindented[write_end:]
    tail = tail[:block_start]+unindented+tail[block_end:]
    required = sorted((names(prelude[prelude.index('\n')+1:], ast.Store) | {'args'}) & names(tail, ast.Load) - names(tail, ast.Store))
    bindings = ''.join(f'    {n} = prepared[{n!r}]\n' for n in required)
    tail = tail.replace('    ensemble_weights = compute_model_weights(pipelines, X_train, y_train)', '    stage_progress("cross_validation", "Cross-validating women’s ensemble weights")\n    ensemble_weights = compute_model_weights(pipelines, X_train, y_train)', 1)
    tail = tail.replace('        pipeline.fit(X_train, y_train)', '        stage_progress("training", "Fitting women’s model: "+model_name, completed=len(predictions), total=len(pipelines))\n        pipeline.fit(X_train, y_train)', 1)
    tail = tail.replace('    pred_df = pd.DataFrame(predictions)', '    stage_progress("prediction", "Combining forward/reverse estimates and reliability")\n    pred_df = pd.DataFrame(predictions)', 1)
    helper = '''
def comparison_from_prepared(prepared):
    p = prepared
    result = dict(fighter_a=p['fighter_a'], fighter_b=p['fighter_b'],
                  fight_date=p['fight_date'].strftime('%Y-%m-%d'), division=p['args'].division,
                  model_version='v1_current_ensemble', result_state='comparison',
                  warnings=list(p['manual_profile_warnings']))
    for side in ('a', 'b'):
        snapshot = p['snapshot_'+side]
        prefix = 'fighter_'+side+'_'
        live = {str(c)[len(prefix):]:v for c,v in p['pred_row_forward'].iloc[0].items() if str(c).startswith(prefix)}
        result[prefix+'snapshot'] = snapshot
        result[prefix+'comparison'] = {**snapshot, **live}
        dates = p['hist_stats'].loc[p['hist_stats']['fighter']==p['fighter_'+side], 'event_date'].dropna()
        result[prefix+'comparison']['history_max_event_date_before'] = dates.max().strftime('%Y-%m-%d') if not dates.empty else None
    return json_safe_value(result)


def predict_prepared_matchup(prepared, progress=None):
'''
    new = text[:start]+prelude+'    return locals()\n\n'+helper+'    notify = progress or stage_progress\n'+bindings+tail.replace('stage_progress(', 'notify(')+'\n    return json_safe_value(summary)\n\n\ndef main():\n    prepared = prepare_matchup(parse_args())\n    return predict_prepared_matchup(prepared)\n'+text[ending:]
    new = new.replace('def prepare_matchup(args, progress=None):', 'from analyzer_protocol import progress as stage_progress\n\n\ndef prepare_matchup(args, progress=None):', 1)
    return new

def adapt(root):
    root = Path(root)
    for rel, fn in [('mens_ufc_model/src/prediction/prediction_engine.py', adapt_men), ('womens_ufc_model/predict_matchup_advanced.py', adapt_women)]:
        p = root / rel
        value = fn(p.read_text(encoding='utf-8'))
        ast.parse(value)
        p.write_text(value, encoding='utf-8', newline='\n')

if __name__ == '__main__':
    adapt(Path(__file__).resolve().parents[1])
