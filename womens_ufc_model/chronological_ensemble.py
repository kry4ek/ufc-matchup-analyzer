"""Women's candidate policy: dated weighting and disjoint sigmoid calibration.

Split metadata never enters model features. Every calibrated estimator contains
the complete preprocessing pipeline, fitted exclusively on its training block.
"""
from __future__ import annotations
import math
import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import GradientBoostingClassifier, RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import log_loss

POLICY = 'v2_chronological_calibrated_ensemble'
SPLIT_POLICY = 'event-date-expanding-3_calibration-latest-20pct-v1'

def metadata(frame):
    required = {'fight_id', 'event_date', 'fighter_a_won'}
    if not required.issubset(frame):
        raise ValueError('Chronological model requires bout IDs, dates and labels')
    rows = frame[list(sorted(required))].reset_index(drop=True).copy()
    if rows.isna().any().any() or not rows['fighter_a_won'].isin([0, 1]).all():
        raise ValueError('Invalid split metadata')
    rows['fight_id'] = rows['fight_id'].astype(str)
    if rows['fight_id'].str.strip().eq('').any():
        raise ValueError('Missing bout identity')
    rows['event_date'] = pd.to_datetime(rows['event_date'], errors='raise').dt.normalize()
    for identity, group in rows.groupby('fight_id', sort=False):
        if len(group) != 2 or group['event_date'].nunique() != 1 or set(group['fighter_a_won']) != {0, 1}:
            raise ValueError('Expected exactly two consistent mirrored rows: ' + identity)
    return rows

def audit_split(rows, train, test, kind):
    a, b = rows.iloc[train], rows.iloc[test]
    overlap = set(a.fight_id) & set(b.fight_id)
    if not len(a) or not len(b) or overlap or a.event_date.max() >= b.event_date.min():
        raise ValueError('Invalid chronological ' + kind + ' boundary')
    if len(set(a.fighter_a_won)) != 2 or len(set(b.fighter_a_won)) != 2:
        raise ValueError('Both classes required in each fitting partition')
    if a.fight_id.nunique() < 20 or b.fight_id.nunique() < 10:
        raise ValueError('Insufficient independent bouts for chronological ' + kind)
    return dict(kind=kind, train_bouts=int(a.fight_id.nunique()), test_bouts=int(b.fight_id.nunique()),
                train_max=a.event_date.max().date().isoformat(), test_min=b.event_date.min().date().isoformat(),
                overlapping_bouts=len(overlap), train_indices=train.tolist(), test_indices=test.tolist())

def weighting_splits(rows):
    dates = np.array(sorted(rows.event_date.unique()))
    if len(dates) < 16:
        raise ValueError('At least 16 event dates required; statistics remain available')
    blocks = np.array_split(dates, 4)
    result = []
    for block in blocks[1:]:
        train = np.flatnonzero(rows.event_date < block[0])
        test = np.flatnonzero(rows.event_date.isin(block))
        audit_split(rows, train, test, 'ensemble weighting')
        result.append((train, test))
    return result

def calibration_split(rows):
    dates = np.array(sorted(rows.event_date.unique()))
    if len(dates) < 5:
        raise ValueError('Insufficient event dates for chronological calibration')
    boundary = dates[max(1, min(len(dates)-1, int(len(dates)*.8)))]
    train = np.flatnonzero(rows.event_date < boundary)
    calibration = np.flatnonzero(rows.event_date >= boundary)
    audit_split(rows, train, calibration, 'calibration')
    return train, calibration

def base_models():
    return {
        'gb_shallow_primary': GradientBoostingClassifier(random_state=42, n_estimators=150,
            learning_rate=.03, max_depth=2, subsample=.80),
        'cal_rf_sigmoid_challenger': RandomForestClassifier(random_state=42, n_estimators=500,
            max_depth=4, min_samples_leaf=8, class_weight='balanced', n_jobs=1),
        'logistic_c025_sanity': LogisticRegression(max_iter=5000, class_weight='balanced', C=.25, solver='lbfgs'),
    }

def fit_calibrated(model, frame, features, numeric, categorical, build_pipeline):
    rows = metadata(frame)
    train, calibration = calibration_split(rows)
    # The complete preprocessor is inside the calibrated estimator. Explicit
    # single-fold ensemble mode permits an initial training-only date block.
    pipeline = build_pipeline(model, numeric, categorical)
    estimator = CalibratedClassifierCV(estimator=pipeline, method='sigmoid',
        cv=[(train, calibration)], ensemble=True, n_jobs=1)
    estimator.fit(frame[features], rows.fighter_a_won)
    return estimator, audit_split(rows, train, calibration, 'calibration')

def fit_ensemble(frame, features, numeric, categorical, build_pipeline, progress=None):
    frame = frame.reset_index(drop=True)
    rows = metadata(frame)
    audits, losses = [], {name: [] for name in base_models()}
    for fold, (train, test) in enumerate(weighting_splits(rows)):
        boundary = audit_split(rows, train, test, 'ensemble weighting')
        boundary['fold'] = fold
        for name, model in base_models().items():
            if progress: progress('cross_validation', 'Chronological validation: ' + name,
                                  completed=fold, total=3)
            estimator, inner = fit_calibrated(model, frame.iloc[train].reset_index(drop=True),
                features, numeric, categorical, build_pipeline)
            inner['outer_fold'] = fold
            inner['model'] = name
            # Indices in inner audits are intentionally relative to outer train.
            inner['parent_train_indices'] = train.tolist()
            audits.append(inner)
            p = estimator.predict_proba(frame.iloc[test][features])[:, 1]
            losses[name].append(float(log_loss(rows.iloc[test].fighter_a_won, p, labels=[0, 1])))
        audits.append(boundary)
    weights = {name: 1 / float(np.mean(values)) for name, values in losses.items()}
    total = sum(weights.values())
    if not math.isfinite(total) or total <= 0:
        raise ValueError('Invalid chronological ensemble weights')
    weights = {name: weight / total for name, weight in weights.items()}
    fitted = {}
    for index, (name, model) in enumerate(base_models().items()):
        if progress: progress('training', 'Fitting chronological model: ' + name,
                              completed=index, total=len(weights))
        fitted[name], boundary = fit_calibrated(model, frame, features, numeric, categorical, build_pipeline)
        boundary['model'] = name
        boundary['final'] = True
        audits.append(boundary)
    return fitted, weights, dict(policy=POLICY, split_policy=SPLIT_POLICY, status='PASS',
        training_bouts=int(rows.fight_id.nunique()), weighting_losses=losses, boundaries=audits)
