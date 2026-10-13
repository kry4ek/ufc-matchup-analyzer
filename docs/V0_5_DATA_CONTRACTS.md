# v0.5 frozen records and cache contracts

The public app keeps history schema 1 and its existing 50-entry/50-MB budget. Optional v0.5 fields are saved inside the integrity-protected payload. Older entries remain readable; missing evidence is explicitly unavailable. Opening a saved report never rebuilds its summary or fight evidence from current datasets.

## Calculation artifacts

`analyzer_cache.py` owns `.runtime/compute_cache`. Manifest schema 1 records artifact kind, compatibility-key hash, serialized size and content SHA-256. Keys include dataset contents, all selected engine/app code, dependency versions, Python version, model family, app/report version, dates/cutoffs, division, worker settings, optional manual-profile contents and canonical app location. Fighter names/IDs are excluded only for the proved shared boundaries. Moving the app invalidates objects that can contain absolute resource paths.

Men reuse parsed resources, a complete dated Bayesian history context and the fitted model. Women reuse dated Elo state, parsed Bayesian statistics/priors and the fitted ensemble plus its cross-validation weights. Training and inference algorithms are unchanged. Prepared fighter snapshots, forward/reverse inference and reliability calculations remain specific to the requested matchup.

Artifacts are locally generated cloudpickle objects, with matching manifests and hashes checked before deserialization. They are excluded from source, dataset and portable archives. Cache storage is optional: failures or incompatible/corrupt objects fall back to computation. Atomic temporary-file replacement and the app operation lock prevent incomplete entries being used. The default binary-artifact budget is 1 GiB; small companion manifests add a little overhead. Recalculate bypasses both saved-result and computational-cache reads. Clearing computational artifacts preserves saved reports and recovery data.

## Correction previews

Preview schema 1 contains a timestamp/UUID identifier, inclusive requested range, all baseline dataset hashes, completed event identities/metadata, complete captured source tables, original safety audit and field-level differences. An integrity hash covers the entire record. The default range is 90 days and a request is limited to 20 events, with no silent truncation.

Source values are canonicalized for whitespace, numeric formatting and midnight date formatting. Missing values remain distinct from zero. Existing fighter/fight IDs must match; known missing bouts/events, incomplete pairs and inconsistent linked raw/stat outcomes block replacement. Name changes that need reconciliation in the women's name-based engine are blocked. Ten recent preview-attempt directories are retained.

Apply uses this captured record without fetching again, reacquires the operation lock, verifies baseline hashes/integrity and repeats paired/link/field audits. It replaces full source records in private staging, chronologically rebuilds affected derived data and invokes the existing all-target journal/promotion/recovery machinery. Summaries count corrected/added fights and added/removed/net binary rows independently. Draw/NC statistics survive while binary labels stay empty. Restore returns exact previous file contents. Historical cutoffs use installed facts, which can include later corrections.

## Summary and metric evidence

Summary schema/rules version 1 records up to three ordered observations, up to two limitations, evidence IDs, frozen raw values/units/definitions/support and rendered text. Thresholds are presentation choices rather than significance tests. Experience differences need three fights; activity differences need 60 days; Elo/opponent-rating differences need 100 points and at least five recorded fights per fighter. Smoothed accuracy/defense observations need a ten-percentage-point difference and at least 20 supporting attempts per fighter. Unsupported per-minute rate comparisons are suppressed.

Each frozen metric record has a stable source-field ID, semantic version, unit, engine-defined history window, explanation, raw values and support notes. A future definition change must increment its semantic version. Summaries use the same prepared evidence in Overview, supporting-metric navigation and complete clipboard/TXT/HTML output. They do not explain model probabilities or add a new confidence grade.

## Saved-version comparisons

Comparison schema 1 holds independent copies of both validated history records. The same sex/model family and two unambiguous stable fighter IDs are required; reversed ordering is normalized to the original. Generation dates, division/date/settings/cutoffs and dataset/code/runtime changes remain visible. Compatible metric definitions can be subtracted; missing/incompatible values stay unavailable. Probability and percentage metrics use percentage-point deltas.

Full eligible-fight evidence stores source fight IDs, dates, outcomes, opponent identities and canonical paired-source fingerprints. It covers all eligible recorded bouts, separately from the last-five display, so a dropped last-five row does not become a false dataset-removal claim. Added eligibility, lost eligibility and changed records are distinguishable. Full raw source CSVs are never saved in each report. Coverage changes and before/after evidence are included in offline comparison exports. Multiple changed inputs do not establish the cause of a probability change. Open comparisons continue to work if the underlying history is later pruned.
