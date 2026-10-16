# v0.7 evidence and research contracts

Status: implemented evidence schema; candidate model promotion remains gated by research results.

`evidence_quality` schema 1 is optional on saved reports. It freezes canonical
identity, division, history/training cutoffs, source fingerprint, data-through
date, per-fighter recorded bout coverage, known attempt support, and evaluation
provenance at generation time. Initial records are explicitly partial;
statistics-only records contain no probability or prediction-reliability claim.

Recorded bouts can include draws/no-contests; binary training excludes these
outcomes. Division counts measure selected-division experience. Rate support
uses explicit attempt denominator fields; zero denominator for a smoothed rate
is prior-only, while unavailable denominator remains unavailable. Profile
measurements can reflect later corrections.

Evaluation compatibility is `matches`, `different_model`, `different_engine`,
`different_data`, `unknown`, or `unavailable`. Methodology status is separate:
matching source hashes cannot clear a failed audit. Empty provenance cannot
produce a match. Evaluation artifacts remain bounded to 2 MiB, integrity-checked,
structurally checked, and constrained to local paths.

Native Overview, details, clipboard, TXT and offline HTML use the same formatter
and frozen object. Reopening/importing a report never reads current datasets to
fill missing facts. Older reports state that evidence-quality details were not
recorded. Invalid evidence schemas/counts block import; originals remain intact.
The reviewed validation artifact hash participates in saved-result reuse. A
changed evaluation artifact requires a newly captured report, while compatible
arithmetic caches can still be reused because that presentation-only hash is
excluded from their computation context.

The women's parent candidate policy is `v2_chronological_calibrated_ensemble`.
Its split policy uses three expanding event-date weighting folds. Each component
fits its complete preprocessor/estimator on the earliest 80% of eligible dates
and calibrates sigmoid probabilities on the latest 20%. Within an outer fold,
the calibration split is rebuilt relative to that fold's training subset.
Final fitting uses the same 80/20 policy. Mirrored pairs remain together at all
boundaries; all training dates precede calibration/validation dates. At least
20 fitting bouts and 10 held-out bouts are required at each boundary, and
weighting requires 16 event dates. Insufficient support returns prediction
unavailable; operational failures cannot silently select fallback weights.

Base model settings remain the retained GB/RF/logistic settings. Sequential
fitting bounds nested CPU use. Calibration deliberately leaves the latest 20%
of dates out of the corresponding base estimator; this is a model policy change
that requires evaluation, not a numerical-parity optimization.

Research protocol and checkpoint records include code/data signatures, dates,
exposure exclusions, complete planned/scored/failed/remaining accounting, and
per-event attempts. Input changes require a new registered run. Stored-feature
evaluation is explicitly distinct from live-app parity verification. Raw
forecasts and checkpoints stay outside public source artifacts.
