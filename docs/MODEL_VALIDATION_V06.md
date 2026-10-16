# Model validation — limited retrospective evaluation

Reviewed: 2026-10-13T11:12:34+00:00

One decisive bout per observation; fighter orientation uses stable IDs. Development precedes 26 September 2026. The 26 September holdout was frozen before scoring; no tuning. Training excludes the selected date and later. Five fixed probability bins; log-loss clipping at 1e-12. Baselines use 50/50 and unmodified pre-bout Elo expected scores. Event-aware uncertainty is unavailable with fewer than five event/date clusters. Repeated fighters can remain dependent.

```text
MODEL VALIDATION
LIMITED_RETROSPECTIVE_EVALUATION
Protocol: v06-frozen-20261013-1
Period: 2026-09-19 through 2026-09-26
Frozen holdout begins: 2026-09-26; scores and calibration below use holdout bouts only.
Snapshot evaluation includes later source corrections. This is not prospective performance.
Accuracy: fraction of correct choices. Brier score: squared probability error; lower is better.
Accuracy chooses fighter A at probabilities of 50% or higher, including exact 50/50 ties; orientation uses stable IDs.
Log loss penalizes confident errors; lower is better. Calibration compares probability bins with observed outcomes.

Report reviewed: 2026-10-13T11:12:34+00:00
Small two-event/date evaluation; not evidence of general accuracy or profitability.
Existing women ensemble uses shuffled, ungrouped folds; mirrored bouts cross training/validation folds. Internal calibration also uses ungrouped stratification. Outer evaluation remains strictly chronological; internal CV is not a clean accuracy estimate.
No algorithm tuning or calibration changes. Corrected snapshot does not reconstruct historical publication state.
Mirrored-fold defect needs a separately validated parent model correction; this report does not clear that methodological gate.

MEN — v3_bayes_smoothed
Evaluated: 20; excluded: 0; failed: 0; remaining: 0
Scored holdout bouts: 9
Model holdout: accuracy=0.6667, brier=0.1992, log_loss=0.588
50/50 holdout: accuracy=0.5556, brier=0.25, log_loss=0.6931
Elo holdout: accuracy=0.6667, brier=0.2445, log_loss=0.6821
Probability 0%–20%: n=0, mean forecast=None, observed=None
Probability 20%–40%: n=5, mean forecast=0.36462139737959803, observed=0.2
Probability 40%–60%: n=3, mean forecast=0.49938080529379114, observed=1.0
Probability 60%–80%: n=1, mean forecast=0.7133572150033518, observed=1.0
Probability 80%–100%: n=0, mean forecast=None, observed=None
Event-cluster bootstrap: {'status': 'Unavailable: fewer than five independent event/date clusters', 'clusters': 1}; repeated fighters remain dependent.

WOMEN — v1_current_ensemble
Evaluated: 4; excluded: 0; failed: 0; remaining: 0
Scored holdout bouts: 3
Model holdout: accuracy=1.0, brier=0.2187, log_loss=0.6303
50/50 holdout: accuracy=0.3333, brier=0.25, log_loss=0.6931
Elo holdout: accuracy=0.3333, brier=0.2499, log_loss=0.6929
Probability 0%–20%: n=0, mean forecast=None, observed=None
Probability 20%–40%: n=0, mean forecast=None, observed=None
Probability 40%–60%: n=3, mean forecast=0.48579438623188237, observed=0.3333333333333333
Probability 60%–80%: n=0, mean forecast=None, observed=None
Probability 80%–100%: n=0, mean forecast=None, observed=None
Event-cluster bootstrap: {'status': 'Unavailable: fewer than five independent event/date clusters', 'clusters': 1}; repeated fighters remain dependent.
```

[Offline calibration diagrams](MODEL_VALIDATION.html) include every bin and its sample count. Empty bins remain unavailable.

## Next research cycle

The next model research cycle must keep mirrored bout pairs together in ensemble and calibration folds, use chronological outer evaluation, and audit calibration on disjoint bout groups. Compare against the frozen current policy without retuning this holdout. Promote a changed model only after a separate protocol and evaluation.

A prospective research ledger should record each forecast, request, model/data fingerprints and timestamp before an event, then append outcomes and scores afterward. Retain every planned forecast and failure. Independently verifiable publication timestamps are needed for a prospective claim; local clocks and the app's prunable recent-history list are insufficient. Do not rewrite earlier forecasts.
