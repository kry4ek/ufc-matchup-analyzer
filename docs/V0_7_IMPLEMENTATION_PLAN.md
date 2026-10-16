# v0.7 implementation plan

Prepared: 14 October 2026. Implementation authorized on 14 October; local implementation and registered model review completed on 15 October 2026. Evidence is recorded in [v0.7 verification](V0_7_VERIFICATION.md), with delivery-specific proof beside the archives. The corrected women's policy passed its promotion gates. Publication remains a separate action.

On 15 October the user accepted recording unavailable clean Windows 10/11 and actual display-scaling tests as outstanding release checks. The user also requested a dataset refresh: validated October data is synchronized parent first, while the registered September evaluation inputs remain frozen separately. These adjustments do not clear the stable-release gates.

## Intended outcome

Deliver a Windows-first, single-matchup release with a corrected and explicitly evaluated women's model, measured improvements to fresh-analysis latency, a compact evidence-quality block beside the probability, and completed Windows compatibility checks.

The research parent remains the source of model algorithms. This repository owns the public app, reviewed engine exports, packaging, and user-facing reports. Keep the men's current model as the control unless its audit finds a separate correctness defect. Start a prospective forecast ledger in the research workspace, but do not make accumulated prospective results a prerequisite for the app release.

Retain existing initial evidence, charts, summaries, saved comparisons, transactional updates, correction previews, import/undo, and offline operation. Full-card analysis, odds feeds, betting recommendations, new chart collections, a UI-framework rewrite, and automatic application updates are outside this release.

## Planning evidence and boundaries

- The app checkout was clean before this plan and was at `6b702b56c89fbe7727ea70995bd0cd79c0eaa89a`, with version 0.6.0 in the README. Recheck this before implementation.
- The existing validation report documents mirrored-bout overlap in women's ensemble and calibration folds. Its final holdout contains nine men's bouts and three women's bouts.
- Code inspection confirms `build_ensemble_cv()` uses shuffled `StratifiedKFold`, `calibration_cv()` returns integer fold counts, and `compute_model_weights()` calls `cross_val_score()` on already constructed pipelines. Changing only the outer splitter will not address nested calibration.
- Recorded v0.6 portable runs took 120.480 seconds for men and 152.745 seconds for women. These are functional observations, not controlled benchmark baselines for v0.7.
- Coverage, metric support notes, report fingerprints, and validation artifacts already exist. Reuse them instead of creating competing definitions.
- The research-parent directory exists, but this planning pass did not audit its working state or validate its current engine parity. Verify it before editing or exporting.
- No tests were rerun for this planning-only change. Historical passing counts are not v0.7 evidence.

References: [model report](MODEL_VALIDATION.md), [v0.6 verification](V0_6_VERIFICATION.md), [model notes](MODELS.md), [contributing](../CONTRIBUTING.md), [publishing](PUBLISHING.md).

## Delivery sequence

| Milestone | Work | Dependency | Exit condition |
| --- | --- | --- | --- |
| M0 | Baseline, environment, and checkpoints | None | Reproducible current behavior and known inputs |
| M1 | Evaluation protocol and evidence contracts | M0 | Frozen definitions before candidate scoring |
| M2 | Parent model correction and leakage audits | M1 | Clean nested splits and reproducible candidate |
| M3 | Broader evaluation and model decision | M2 | Complete accounting and documented promotion decision |
| M4 | Fresh-analysis performance | M0 profile; final work after M3 | Measured improvement against identical model semantics |
| M5 | Evidence-quality UI and exports | M1; final integration after M3 | Frozen evidence agrees across all views |
| M6 | Prospective research ledger | M1; candidate forecasts after M3 | Resume-safe ledger and dry-run lifecycle verified |
| M7 | Integrated portable and Windows matrix | M3–M5 | Candidate workflows and real platform checks complete |
| M8 | Handoff and conditional publication | M7 | Reviewable package; publication proof if publishing is requested |

Execution order: M0 → M1 → M2 → M3 → M4 → finish M5 → M7 → M8. M5 can be built against fixtures while M3 runs; M6 can begin with the protocol. Run expensive jobs sequentially on the reference machine whenever they would distort timings. Identify Windows test machines early so availability does not become a late surprise.

## M0 — Establish a reproducible baseline

### Step 1. Confirm source ownership and working state

1. Inspect app and parent Git state, applicable repository instructions, current branches, runtime versions, source/data manifests, and actual resolved paths. Preserve unrelated changes and the separately installed portable.
2. Create `codex/v07-validation-performance` for app implementation when implementation starts. Use a separately tracked parent branch or equivalent clean parent snapshot for research changes.
3. Record the parent source revision and original/exported hashes from `source_manifest.json`. Reproduce the existing export into a new disposable directory and explain differences before editing engines.
4. Use `work/v07-validation/` for local app evidence and the parent's own work area for raw research results. Keep generated predictions, caches, profiles, and machine paths out of public source.
5. Inventory available clean Windows 10/11 x64 systems or VMs and actual display-scale settings. A machine that cannot be accessed is an explicit outstanding check, not an assumed pass.

**Deliverable:** baseline manifest identifying source, data, dependencies, machine, model policy, existing failures, and test-environment availability.

### Step 2. Capture current behavior

1. Run the existing data-equipped unittest suite, setup checks, and release audit using the verified local interpreter. Confirm all 15 datasets match their manifests.
2. Capture both model families for ordinary, reversed-order, historical, sparse-history, division-change, manual-profile where supported, and statistics-only requests. Add zero-history and ambiguous-identity failures.
3. Save probabilities, component weights, raw comparison values, cutoffs, warnings, reliability outputs, charts' numeric evidence, histories, and TXT/HTML exports.
4. Exercise exact-result reuse, cross-matchup cache reuse, forced recalculation, cancellation, viewing an old report during a job, update/restore, and migration/undo on disposable installations.
5. Record reproducible first-evidence and final-result timings. This preliminary profile identifies likely bottlenecks; the controlled optimization benchmark is Step 14.

**Acceptance:** baseline failures are understood; the reference cases and input fingerprints can be replayed. Do not start with an unexplained failing baseline.

### Step 3. Add durable progress records

1. Create a local `RESUME-CHECKPOINT.md` with the active milestone, completed checks, exact evidence paths, current worker identity, next safe action, and known blockers.
2. Give each research run a protocol/input signature and isolated output directory. Record per-bout attempts and outcomes durably; use atomic snapshots as an index over retained records.
3. Checkpoint after each completed bout and milestone. On restart, reconcile completed artifacts and workers before scheduling more work.
4. Resume only when protocol, code, data, and model fingerprints match. Changed inputs start a new run; failed attempts remain recorded even when a later retry succeeds.

**Acceptance:** an interrupted small evaluation resumes without overwriting completed evidence or duplicating scored bouts.

## M1 — Freeze the research protocol and app contracts

### Step 4. Define the broader evaluation cohort

1. Inventory dates, unique bouts, events, labels, identities, and feature availability using metadata only. Audit prior research exposure before choosing the final test interval.
2. Planning default: cover up to 36 months of available supported history, with the earlier 24 months used for development diagnostics and the latest 12 months reserved for final evaluation. Actual boundaries must be frozen after coverage/exposure review and before candidate scores are examined.
3. If that final interval has already driven model selection, choose a genuinely unused interval before scoring or label the available results retrospective development evidence. Do not describe reused data as an untouched test set. The two dates scored for v0.6 remain explicitly identified; any exclusion from the new final-test claim is predetermined and separately reported.
4. Use every eligible bout in the declared cohort. Count one observation per decisive bout with stable-ID orientation. Record every unsupported division, draw/NC, identity problem, missing feature case, failure, and unresolved case with a reason.
5. Freeze chronological event/date blocks: all training precedes the evaluated date, including other events on the same date. Keep both mirrored training rows of a bout together in every split.
6. Retain the current policy as a frozen reference and compare the corrected candidate on the same planned cases. Evaluate the unchanged men's model over the broader cohort too.
7. Select log loss as the primary probability-quality metric, with Brier score, accuracy, calibration bins/counts, and 50/50 and pre-bout Elo baselines. Freeze tie handling, clipping, bin edges, and subgroup definitions.
8. Use paired event/date resampling for candidate-versus-reference uncertainty where the number of clusters supports it. Report counts and repeated-fighter dependence; a large row count alone does not establish independent evidence.
9. Fix the required final sample and event counts, material-regression margins, and uncertainty method in the protocol before viewing candidate results. Choose them from coverage and the intended precision, not from favorable scores. Small subgroups remain descriptive.
10. Pilot runtime using development cases only, estimate total computation and disk space, and then lock the run. If the full cohort is infeasible, document a prospectively defined smaller design before scoring; never stop after favorable results.

**Deliverable:** a parent-owned v0.7 protocol plus a public summary of its dates, inclusion rules, counts, metrics, exposure limitations, resource estimate, and decision rules.

### Step 5. Define the evidence-quality payload

Add an optional, versioned `evidence_quality` object to newly generated report payloads. Prefer a small dedicated builder, provisionally `analyzer_evidence.py`.

| Field group | Required meaning |
| --- | --- |
| Identity and context | Canonical fighter IDs, selected division/date, history cutoff, training cutoff, generation time |
| Fighter history | Eligible recorded bouts, selected-division bouts, latest eligible bout, explicit missing reason |
| Metric support | Stable metric ID, known attempt denominator, smoothing/prior-only status, missingness reason |
| Source snapshot | Dataset fingerprint and data-through dates for the relevant model family |
| Model evaluation | Model policy ID, evaluation artifact hash, protocol ID, evaluated engine/data fingerprints, methodology status |
| Scope | Initial/advanced/final/statistics-only state and schema version |

1. Derive facts from the same validated context as the displayed result. Do not independently reload current data when reopening a report.
2. A bout count describes recorded history, not attempts supporting an individual rate. Draws/NCs can contribute history while remaining outside binary training labels.
3. Preserve zero versus unavailable. Declare a value prior-only only when the engine supplies enough information to establish it; do not infer this from a small bout count.
4. Separate model-methodology status from fingerprint compatibility. Matching an evaluated snapshot does not mean the model passed its methodology audit.
5. Separate saved generation-time facts from a current-installation compatibility notice. The latter can change after an update; it must not rewrite the saved result or its original export evidence.
6. Initial evidence contains only fields already available, labelled partial. Statistics-only reports contain no prediction-quality claim or probability.
7. Older reports show that this block was not recorded. Render any supported legacy facts explicitly as legacy saved evidence; do not backfill from current datasets.
8. Add an artifact schema revision only if needed. Continue reading the v0.6 validation artifact and older saved-report schemas. Define size limits and invalid-artifact behavior.

**Deliverable:** `docs/V0_7_DATA_CONTRACTS.md`, small examples for each report state, and compatibility fixtures.

## M2 — Correct model methodology in the research parent

### Step 6. Trace every fitting boundary

1. Audit parent equivalents of `calibration_cv()`, `build_ensemble_cv()`, `build_models()`, `compute_model_weights()`, `build_model_pipeline()`, and `predict_prepared_matchup()`.
2. Follow stable bout IDs and event dates through filtering, ordering, mirrored-row creation, and feature selection. These identifiers belong to split metadata, not predictive features.
3. Audit fitted preprocessing, smoothing priors, feature generation, calibration, ensemble weights, and any reliability thresholds. Identify which are fixed policies and which learn from data.
4. Verify that stored historical features were generated using strictly earlier information. If a feature or prior uses future information, correct and regenerate it in the parent before evaluating the candidate.
5. Audit the men's route for the same categories of leakage without assuming it shares the women's defect. A newly found defect receives its own documented correction and policy version.

**Acceptance:** a written map shows what is fitted on which rows at each nested level.

### Step 7. Implement chronological splits that preserve bouts

1. Build deterministic expanding-window splits over unique event dates, with training dates strictly earlier than validation dates. Never split an event date or a mirrored bout between partitions.
2. Construct explicit split indices relative to each local training subset. Rebuild inner indices for every outer fold; full-dataset indices must not be reused inside a subset.
3. Pass the required IDs/dates explicitly through model fitting. Prefer an explicit fold loop when generic cross-validation wrappers make nested grouping difficult to audit.
4. Ensure learned preprocessing is fitted only on each inner training partition. Wrapping a calibrated estimator inside a pipeline does not by itself prove preprocessing isolation; inspect the actual nesting and place the complete preprocessing/estimator pipeline inside the appropriate fitting boundary.
5. Fit each calibrator on predictions for bouts excluded from that underlying estimator's fitting data. Ensemble-weight validation bouts must also be excluded from the corresponding component training and calibration.
6. Freeze minimum training history, fold count policy, warm-up rows, minimum class/group requirements, and insufficient-history behavior. Do not fall back to shuffled row splits when chronological folds are sparse.
7. For insufficient data, use only a prespecified and evaluated reduced-fold/uncalibrated policy with a clear label, or return prediction unavailable while retaining statistics. Operational errors remain errors, never a trigger for silent fallback weights.
8. Verify the implementation against the pinned scikit-learn version. Do not assume a generic time splitter works with every calibration mode: some modes require out-of-fold predictions covering a full partition, whereas expanding windows leave an initial training-only block.

**Acceptance:** every fitting/calibration/weighting boundary has zero overlapping bout IDs and passes its declared chronology assertions. Missing metadata fails closed.

### Step 8. Test the correction before expensive evaluation

1. Use synthetic fixtures with mirrored rows, same-date events, reordered indices, duplicated IDs, missing dates, small histories, and insufficient classes.
2. Assert actual membership of nested fit/calibration/validation sets, including preprocessing fits. A test that checks only the splitter class is insufficient.
3. Verify cutoff filtering with adversarial later bouts and target-bout data. Keep draw/NC records in evidence while excluding them from binary labels.
4. Run real development-case fits, checking bounded probabilities, finite weights summing to one, forward/reverse behavior, determinism, cancellation, and errors.
5. Assign the candidate a distinct model policy ID and include it plus split/calibration policy in cache and result fingerprints. Old women's fitted models must never satisfy the new cache key.

**Acceptance:** meaningful leakage tests and development smoke checks pass. Prediction changes from the correction are expected and recorded, not treated as speed-refactor parity failures.

## M3 — Evaluate, decide, and export

### Step 9. Run development evaluation and freeze the candidate

1. Evaluate the reference and candidate on the same development cohort, using the checkpointed runner and single-bout scoring rules.
2. Investigate failures, calibration behavior, materially changed probabilities, and sparse-history cases. Any policy selection uses development evidence only.
3. Freeze candidate code, parameters, split rules, fallback policy, dependencies, protocol, and dataset hashes before running the final test.
4. Keep preprocessing and fitted models specific to each cutoff. Reuse across matchups only when the full training context matches.

### Step 10. Complete the final evaluation

1. Generate forecasts using only each date's eligible training information, without exposing evaluation outcomes to fitting or candidate selection.
2. Save each forecast with full provenance before scoring it. Historical source corrections remain explicitly disclosed; this process is not prospective performance.
3. Reconcile planned = scored + excluded + failed + remaining, with no duplicate bouts. Report paired comparison coverage if one policy fails where another succeeds.
4. Publish aggregate and predefined subgroup metrics with sample sizes, calibration counts, uncertainty where supported, and failure coverage. Keep raw research records local unless separately intended for publication.
5. Produce machine-readable and readable reports from the same records; independently reconcile their totals and sampled probabilities.
6. Do not tune against the final test. A change prompted by those results is a new research cycle with a new evaluation plan.

**Acceptance:** zero unexplained remaining cases; every exclusion/failure is visible; the methodology audit and performance findings are reported separately.

### Step 11. Make the promotion decision

1. Apply the frozen decision rules. Fixing leakage is a correctness requirement; better headline accuracy is not guaranteed.
2. Promote the corrected policy only after clean methodology, reproducibility, acceptable forecast coverage, and the prespecified performance criteria are met. Report inconclusive uncertainty honestly.
3. A weaker corrected score does not justify describing the old leaking policy as validated. If the candidate fails its promotion gate, keep it in research and record M3 as incomplete; any reduced-scope release must explicitly retain the known limitation and must not claim to deliver the model fix.
4. Reassess inherited reliability wording/thresholds against the new policy. If their meaning is unsupported, revise or remove the unsupported assessment rather than presenting it as newly validated.
5. Save the approved candidate's output matrix as the new numerical baseline for all subsequent performance work.

**Deliverable:** a model decision record describing changes, evidence, limitations, and the exact promoted policy, or the explicit reason promotion is blocked.

### Step 12. Export through the established boundary

1. Export selected parent files into a fresh candidate directory with `tools/export_source.py`; review existing workflow and maintenance adapters and any new helper dependencies.
2. Ensure new parent helpers are in the export allowlist, staged maintenance dependency closure where needed, and source provenance. Do not use packaging hash refresh as proof that an engine change came from the parent.
3. Compare parent and exported predictions for both families and all representative cases. The corrected women's outputs must match its new parent baseline; unrelated men's outputs must retain their existing semantics.
4. Verify old saved reports remain viewable and importable, retain their original probabilities, and are not reused as current predictions after policy changes. Model-delta comparisons must identify the policy difference.
5. Export only the reviewed public validation artifact and its summaries. Preserve v0.6 reports as dated history.

**Acceptance:** reproducible export, matching parent/app outputs, correct invalidation, and complete dependency closure.

## M4 — Improve fresh-analysis latency

### Step 13. Instrument the complete request

Record monotonic durations for startup/imports, dataset verification, raw loading, dated feature preparation, advanced population work, ensemble CV, calibration, final fitting, cache I/O, report construction, and rendering. Record peak process-tree memory and worker counts. Distinguish first evidence, advanced comparison, and final result.

Measure men and women separately. Recheck possible nested parallelism in women's cross-validation and random forests before changing worker policy. Keep measurements out of the GUI thread and do not fabricate overall progress percentages or ETAs.

### Step 14. Freeze a controlled benchmark

1. Use the M3 promoted model unchanged on both sides of every optimization comparison. Separately report the total v0.6-to-v0.7 difference, which also includes methodology changes.
2. Define cases: ordinary present-date, historical, changed matchup with a compatible training cutoff, statistics-only, exact saved-result reuse, and forced recalculation for both families.
3. Use at least three alternating baseline/candidate repetitions per primary case on the same idle machine, power mode, runtime, data, and worker policy. Report individual results, median, range, and OS-file-cache conditions.
4. Cold application-cache runs start without app result/calculation artifacts; they do not imply a cold OS boot. Use separate disposable cache directories.
5. After profiling, freeze a realistic end-to-end target. Working objective: at least 20% lower median fresh-prediction latency on the dominant affected route. This is a target, not a promised result; record any adjustment before implementing the optimization.
6. Keep initial evidence within the existing approximately 10-second reference-machine objective, and investigate repeatable regressions above 5% in other primary latency or memory measures. Repeat noisy cases only when needed to resolve uncertainty.

### Step 15. Optimize one measured bottleneck at a time

1. Prefer removing repeated scans/conversions, sharing immutable prepared state, indexing history once, and preventing CPU oversubscription.
2. Reuse fitted work only for identical training inputs and policy. Preserve full content integrity checks and existing bounded, optional caches.
3. Keep features, seeds, tree counts, folds, calibration policy, and model weights unchanged during this phase. Any such change is a model change requiring renewed evaluation.
4. For parent-engine work, implement and verify there, then reproduce the export. App-only orchestration improvements stay in this repository.
5. After each change, compare complete probabilities/component weights and raw metrics against the M3 baseline. Use existing `1e-12` probability expectations and predeclared feature tolerances; investigate drift instead of relaxing tolerances afterward.
6. Check corrupt/unwritable cache, changed data/cutoff/model, moved folders, recalculation bypass, cancellation, and history preservation.

**Acceptance:** controlled measured benefit with output parity and no unexplained responsiveness/memory regression. If the speed target is missed, report the actual result and keep the performance goal open; do not market a partial-stage improvement as faster final prediction.

## M5 — Put evidence quality beside the probability

### Step 16. Build one shared evidence formatter

1. Implement the Step 5 builder using validated coverage, engine support fields, source context, and reviewed validation metadata.
2. Produce concise display rows and detailed explanatory text from the same frozen object. Avoid independent GUI/TXT/HTML calculations.
3. Reuse an already verified request fingerprint for compatibility checks; do not synchronously hash all datasets on every redraw. Missing or empty provenance must yield unknown/unavailable, never a vacuous match.
4. Expose separate states for matching evaluated engine/data, changed engine, changed data, unevaluated policy, missing report, invalid report, and failed methodology. A data change makes the report snapshot-specific; it does not erase historical evaluation evidence.

### Step 17. Integrate the Overview block

1. Place a compact section below the probability and above detailed metrics, with a fighter column for eligible bouts, division experience, and latest included bout.
2. Add a shared line for data-through date and the relevant model's evaluation status. Show the most important support limitations inline and provide a keyboard-accessible details action for the rest.
3. Reuse current warnings and metric explanations. Do not duplicate the same warning across multiple prominent areas or add a new numerical confidence score.
4. Provide links/actions to existing supporting metrics and the validation view. Keep pending/statistics-only states explicit and probability-free.
5. Use text as well as color; support narrow windows and Small/Medium/Large text. Avoid requiring hover to understand a warning.
6. Confirm viewing an older report during a running request preserves that report's block until the user opens the new result.

### Step 18. Preserve history and export behavior

1. Freeze the block into new completed predictions/statistics comparisons and include it in full text, clipboard, TXT, and offline HTML exports.
2. Verify cancellation preserves labelled partial evidence without creating a completed history entry.
3. Reopen and import pre-v0.7 reports, reports generated before a dataset update, and reports from the old women's policy. Keep original facts/timestamps unchanged.
4. Test export escaping, accented names, long warnings, empty histories, unavailable denominators, prior-only estimates, corrupt validation artifacts, and separate engine/data mismatches.
5. Compare displayed and exported values to the saved payload; visually inspect both native UI and offline HTML at representative widths.

**Acceptance:** every value and limitation can be traced to frozen evidence; current compatibility notices cannot silently alter saved historical claims.

**Primary app areas:** new evidence builder, `analyzer_gui.py`, `analyzer_results.py`, `analyzer_reporting.py`, `analyzer_validation.py`, `analyzer_history.py`, `analyzer_comparison.py`, and payload assembly in `ufc_matchup_analyzer.py`.

## M6 — Begin prospective tracking in research

### Step 19. Define the append-only ledger

1. Register intended forecast cohorts and a strict pre-event cutoff before generating predictions, so failures and omitted bouts remain visible.
2. Record forecast ID, stable bout/fighter IDs, event/date, probability, full request, model/code/data fingerprints, protocol version, generation timestamp, and completion/failure state.
3. Append outcomes, cancellations, draw/NC classifications, source corrections, and scores as separate linked records. Never replace an original forecast with a later recalculation.
4. Use idempotent record identities, bounded retries, a single-writer mechanism, and durable checkpoints. Hash chaining can detect local modification but does not independently prove when a forecast existed.
5. Choose a verifiable external timestamp/publication mechanism before making prospective-performance claims. Preparing this workflow does not authorize external publishing; retain local experimental status until the chosen records are actually timestamped through an authorized process.

### Step 20. Verify one complete lifecycle

Run a clearly marked synthetic/dry-run cohort through registration, forecasts, intentional failure, interrupted restart, timestamp-receipt attachment, outcomes, corrections, and scoring. Reconcile all records and prevent late forecasts from counting as pre-event evidence. Real results accumulate after candidate selection; they are not required to finish v0.7.

**Deliverable:** parent ledger tool, schema, replay/reconciliation checks, protocol, and a dry-run report. No forecast-service UI is added to the app.

## M7 — Verify the integrated Windows portable

### Step 21. Run integrated checks and build a candidate

1. Run full data-equipped regression, focused leakage/evidence/cache tests, setup checks, and source/data/dependency audit. Run source-only checks separately and retain their expected skips.
2. Run the corrected parent/app parity matrix, final controlled benchmark, export/history/import workflows, and maintenance update/rebuild/restore checks using disposable copies.
3. Include a mixed decisive/draw/NC maintenance fixture and interruption recovery. Verify all restored dataset hashes, not only the operation's success status.
4. Update version, changelog, model documentation, validation artifacts, screenshot examples where changed, export/package allowlists, manifests, and release checks.
5. Build from the verified runtime unless a necessary dependency change has its own validation. Inspect import/native dependency closure for new parent helpers.
6. Verify archive inventory, member hashes/CRCs, extracted files, and absence of private histories, caches, raw forecasts, local paths, and credentials.

### Step 22. Complete the real OS and scaling matrix

Test the packaged executable on clean Windows 10 and Windows 11 x64 environments without separately installed Python, Git, or development tools, as a standard user. Record exact OS build, hardware/VM configuration, resolution, scale, and whether the environment is physical or virtual.

| Dimension | Required coverage |
| --- | --- |
| Display | Actual Windows 100%, 150%, and 200% scale on both OS versions; record viewport resolution |
| Text/window | Small/Medium/Large app text; normal and narrow windows; keyboard navigation and readable controls |
| Launch | Fresh extraction, spaces/Unicode in path, offline launch, moved complete folder, relaunch |
| Prediction | At least one real fresh men/women prediction per OS; saved fixture layout checks at every scale |
| Data maintenance | Update/no-change, bounded new-data or correction case, cancellation before commit, restore/recovery |
| Reports | Copy, TXT/HTML save, Unicode, browser printing, older history, new evidence block |
| Upgrade | v0.6 folder import, duplicates/conflicts, preferences, undo, original-folder preservation |
| Failures | Unwritable location, incomplete extraction, low space, network failure; actionable recovery information |

1. At each actual scale, inspect Overview, input controls, comparison, chart labels, history, validation, import, error, and Save dialogs. Fix clipping, overlap, unreachable buttons, and broken focus order.
2. Simulated Tk scaling remains supplemental. It does not substitute for changing the Windows display scale and testing the packaged process.
3. Do not repeat long full predictions for every typography combination; use identical frozen fixtures for layout, plus the required real end-to-end cases.
4. If an environment is unavailable, retain the explicit outstanding gate and complete independent work. Do not label the requested Windows matrix complete.

**Deliverable:** `docs/V0_7_VERIFICATION.md`, machine-readable results, screenshots, environment records, and exact candidate hashes.

## M8 — Handoff and conditional publication

### Step 23. Assemble a reviewable local release

Provide the portable ZIP, curated source ZIP, checksums, benchmark comparison, model report/decision record, upgrade notes, and verification report. List every failed or unavailable check next to its impact. Keep dataset-rights status as `review_required` unless supporting clearance evidence actually changes; engineering tests do not establish rights.

The complete app continues to include its matching 15 datasets. Do not add a standalone public dataset ZIP. Keep experimental/prerelease wording wherever the existing stable-release gates remain unresolved, even if model and Windows checks pass.

### Step 24. Publish only as part of an authorized release action

When publication is requested, push curated source, verify CI on the exact release commit across its supported source-check platforms, upload and inspect draft assets, then publish. Download public assets anonymously, verify their hashes/inventory, extract and launch the actual downloaded portable, and run both model-family smoke workflows offline. Save post-publication evidence separately from local candidate checks.

Planning or implementing v0.7 does not itself publish it. No further permission is needed to perform ordinary local implementation and verification within an authorized implementation request.

## Completion criteria

| Area | Required evidence |
| --- | --- |
| Methodology | No bout overlap or forbidden date overlap at any nested fit/calibration/validation boundary |
| Evaluation | Frozen protocol, complete case accounting, broader results, honest uncertainty and exposure limitations |
| Model integration | Explicit policy version, parent/export parity, cache invalidation, preserved legacy reports |
| Performance | Controlled before/after measurements on identical model semantics and retained numerical behavior |
| Evidence UI | Shared frozen facts, clear missing states, consistent native/clipboard/TXT/HTML output |
| Windows | Clean Win10/11 and actual 100/150/200% scale results with environment-specific evidence |
| Research ledger | Append-only lifecycle and restart reconciliation; no unsupported prospective claim |
| Delivery | Verified portable/source artifacts and explicit remaining stable-release limitations |

## Implementation file map

| Area | Existing code to extend or inspect | Proposed artifacts |
| --- | --- | --- |
| Parent model correction | Parent equivalents of women's `predict_matchup_advanced.py` and feature builders | Split helper, policy ID, nested leakage tests |
| Evaluation | Parent `tools/evaluate_matchup_models_v06.py`; app's retained `tools/evaluate_v06.py` as reference | Parent v0.7 runner, protocol, checkpoint journal, reviewed report |
| Export | `tools/export_source.py`, `tools/adapt_workflows.py`, maintenance adapters, `source_manifest.json` | Reviewed helper allowlist and reproducible export proof |
| Performance | `analyzer_cache.py`, engine preparation/fitting, existing v0.5/v0.6 benchmark scripts | `tools/check_v07_performance.py`, comparable benchmark results |
| Evidence presentation | Catalog, results, reporting, validation, GUI, history, comparison | `analyzer_evidence.py`, contracts, focused integration checks |
| Release | Portable build/package/archive tools, CI, release checks | v0.7 verification report and portable QA matrix |

Proposed filenames are implementation targets, not claims that those files already exist. Prefer extending a suitable existing utility over introducing a duplicate framework.

## Methodology references

Related observations and time-ordered observations require explicit split policies; a generic shuffled row split does not address either requirement. See the [scikit-learn cross-validation guide](https://scikit-learn.org/stable/modules/cross_validation.html). Calibration requires separation from base-estimator fitting data, and its cross-validation behavior depends on the selected mode; see [CalibratedClassifierCV](https://scikit-learn.org/stable/modules/generated/sklearn.calibration.CalibratedClassifierCV.html). Verify implementation details against the repository's pinned dependency version before coding.
