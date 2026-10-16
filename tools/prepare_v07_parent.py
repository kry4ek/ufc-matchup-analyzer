"""Apply the explicit parent correction with original sources retained locally."""
from pathlib import Path
import argparse
import hashlib
import json
import shutil

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    p = argparse.ArgumentParser()
    p.add_argument('--parent', type=Path, required=True)
    p.add_argument('--helper', type=Path, required=True)
    a = p.parse_args()
    path = a.parent / 'womens_ufc_model/predict_matchup_advanced.py'
    baseline = a.parent / 'work/v07-research-baseline/womens_ufc_model/predict_matchup_advanced.py'
    if baseline.exists():
        raise ValueError('Baseline already exists; inspect the previous operation before reapplying')
    source = path.read_text(encoding='utf-8')
    old = '''    models = build_models(y_train)
    pipelines = {
        name: build_model_pipeline(model, numeric_features, categorical_features)
        for name, model in models.items()
    }
    ensemble_weights = compute_model_weights(pipelines, X_train, y_train)'''
    if source.count(old) != 1 or source.count('        pipeline.fit(X_train, y_train)') != 1:
        raise ValueError('Parent fitting context differs; refusing an unchecked patch')
    replacement = '''    from chronological_ensemble import fit_ensemble, POLICY
    pipelines, ensemble_weights, fold_audit = fit_ensemble(
        model_train_df, feature_cols, numeric_features, categorical_features, build_model_pipeline)'''
    changed = source.replace(old, replacement).replace('        pipeline.fit(X_train, y_train)',
        '        # Already fitted using disjoint chronological calibration.')
    marker = '        summary["manual_profile_fallback_used"]'
    if marker not in changed:
        raise ValueError('Missing structured report boundary')
    changed = changed.replace(marker,
        '        summary["model_version"] = POLICY\n        summary["fold_audit"] = fold_audit\n' + marker)
    compile(changed, str(path), 'exec')
    baseline.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, baseline)
    helper = path.with_name('chronological_ensemble.py')
    if helper.exists(): raise ValueError('Candidate helper already exists')
    shutil.copy2(a.helper, helper)
    path.write_text(changed, encoding='utf-8', newline='\n')
    (baseline.parent.parent / 'change.json').write_text(json.dumps(dict(
        policy='v2_chronological_calibrated_ensemble', before=sha(baseline), after=sha(path), helper_sha256=sha(helper)), indent=2)+'\n')
    print('Parent candidate installed; original source preserved. Promotion requires evaluation.')

if __name__ == '__main__': main()
