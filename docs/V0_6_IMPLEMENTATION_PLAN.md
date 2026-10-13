# v0.6 implementation plan

Prepared: 13 October 2026. Status: implemented and locally verified as an experimental candidate. Both model-family workflows passed from a fresh portable extraction. Completed evidence and remaining gates are tracked in [v0.6 verification](V0_6_VERIFICATION.md). Publication is conditional on a separate publication request and its applicable checks.

## Intended outcome

Make the Windows portable, single-matchup app useful sooner, easier to interpret, and easier to upgrade. Establish reproducible evidence about the existing models before considering algorithm changes.

Deliver four improvements:

1. A fast initial comparison followed by the existing advanced comparison and prediction.
2. Visual comparisons with explicit units, history windows, and supporting sample sizes.
3. A reviewed prediction-validation report, produced in the research parent and presented in the app.
4. Guided import of saved analyses and preferences from an older portable installation.

The first two are the main product features. Begin evaluation early because its runtime and data-quality findings may affect the schedule. Include migration as a bounded local-folder workflow. Prospective forecast tracking is a follow-up research deliverable, not an expanded prediction service in v0.6.

Retain men's `v3_bayes_smoothed`, women's `v1_current_ensemble`, existing features, calibration, seeds, confidence/reliability policies, historical cutoffs, and transactional dataset maintenance. A speed optimization must preserve numerical behavior. A discovered methodological defect requires a separately documented model correction and validation decision; it must not disappear into a performance refactor.

## Verified planning baseline

The current checkout contains the v0.5 implementation at `ae2aeb4`. Its local verification report records 161 passing tests and completed local portable workflows; these are historical results, not checks performed while writing this plan. The report also states that v0.5 source CI and published-download verification remain outstanding. Recheck actual release status at implementation time.

Existing v0.5 capabilities include content-checked cross-matchup caching, frozen correction previews, deterministic summaries, and comparisons between saved analyses. Do not rebuild these features under new names.

Recorded compatible-repeat medians are approximately 29.4 seconds for men and 13.6 seconds for women. Separately measured fresh native runs were approximately 160.9 and 184.6 seconds. These measurements have different sampling conditions and must not be treated as a new controlled benchmark. Men's population-history traversal is a documented candidate bottleneck, to be reprofiled.

The current workspace path resolves through a junction to the active E-drive project. Use the current verified workspace and its `work/` directory; resolve paths before creating disposable copies. Do not modify the separately installed portable app during development. Research changes belong in the verified research parent, with reviewed exports into this repository.

References: [v0.5 verification](V0_5_VERIFICATION.md), [v0.5 contracts](V0_5_DATA_CONTRACTS.md), [contributing](../CONTRIBUTING.md), [publishing](PUBLISHING.md).

## Delivery sequence

| Milestone | Deliverable | Depends on | Exit condition |
| --- | --- | --- | --- |
| M0 | Current baseline and release-status reconciliation | None | Reproducible baseline, known outstanding gates |
| M1 | Frozen data contracts and evaluation protocol | M0 | Explicit states, definitions, compatibility and metrics |
| M2 | Fast initial comparison | M1 | Useful dated evidence arrives before advanced preparation |
| M3 | Measured cold-path optimization | M2 and profiling | Repeatable speed improvement with output parity |
| M4 | Visual comparisons and exports | M1; integrate after M2 | Every graphic matches frozen evidence |
| M5 | Model evaluation and reviewed report | M1 | Reproducible chronological results and limitations |
| M6 | Portable upgrade import | M1 | Repeatable import, intact originals, crash recovery |
| M7 | Integrated portable candidate and release checks | M2–M6 | Candidate evidence complete; remaining gates explicit |

Recommended execution: M0 → M1 → start M5 research evaluation → M2 → M3 → M4 → M6 → finish M5 report integration → M7. Evaluation can run while independent UI work proceeds, but expensive evaluation and performance benchmarks must not compete on the benchmark machine.

## M0 — Establish the baseline

### Step 1. Reconcile version and release status

1. Inspect Git status, current source version, existing candidate archives, and actual GitHub release/CI status when release work begins.
2. Preserve v0.4/v0.5 evidence as version-specific history. Correct stale current documentation: for example, `docs/MODELS.md` still says fitted models are not serialized, while v0.5 does persist compatible calculation artifacts.
3. Record which v0.5 publication checks remain. Complete them as part of the applicable release workflow; planning v0.6 does not itself publish either version.
4. Create a `codex/` implementation branch from the agreed baseline. Preserve unrelated user work.

### Step 2. Capture reproducible outputs and timings

1. Record source commit, runtime/dependency versions, model settings, dataset hashes, machine specifications, and power conditions.
2. Create disposable validation copies under `work/v06-validation`. Keep datasets, original user history, and the installed app intact.
3. Capture men's and women's ordinary, reversed-order, historical, sparse-history, division-change, and statistics-only cases. Include valid draw/NC source history and unsupported/ambiguous identities.
4. Save raw metrics, final/component probabilities, reliability information, warnings, recent fights, summaries, calculation context, and export text.
5. Run the existing data-equipped regression suite, setup checks, and release audit. Resolve baseline failures before measuring new behavior.
6. Benchmark cold calculation-cache runs, compatible cross-matchup runs, and exact saved-result reuse separately. Define cold as no app calculation artifacts; identify whether OS file caches were warm. Do not claim a cold system boot unless measured.
7. Use at least three controlled repetitions per representative performance case; retain individual timings, median, and range. Record startup separately from Analyze-to-first-evidence and Analyze-to-final-result.

**Deliverables:** baseline manifest, frozen outputs, phase timings, and a short benchmark protocol under the local validation directory. No generated forecasts or local paths enter public source artifacts.

## M1 — Define contracts before implementing UI

### Step 3. Define the initial-comparison state

1. Add a versioned `quick_comparison` payload with stable fighter identities, selected division/date, relevant cutoffs, dataset fingerprint, generation time, available fields, and missing-data reasons.
2. Distinguish three stages: initial comparison, advanced comparison, and completed prediction. A statistics-only request terminates at the advanced comparison.
3. The initial stage contains no probability, winner, confidence grade, or model-derived summary. It must not populate advanced fields with approximations using the same names.
4. Specify which fields can arrive initially: eligible fight counts, recent results, known profile measurements, and only those basic statistics whose definitions and cost have been verified. Exclude expensive or ambiguous fields from the initial release.
5. Label profile measurements as values in the installed snapshot, since later profile corrections may be present. Historical fight evidence excludes the selected date and later dates.
6. Retain the distinction between fight-history cutoff and any earlier training cutoff. Record both where applicable.
7. Define how cancellation/failure preserves an explicitly partial view and partial TXT/HTML export, without saving it as a completed analysis or reusing it as a successful prediction.

### Step 4. Define visualization and evaluation records

1. Reuse stable metric IDs, semantic versions, units, history windows, and support notes from existing report evidence.
2. Define optional frozen `visual_evidence` containing bar values/support and dated Elo points with source fight IDs. Store raw values, not rendered pixel positions.
3. Define missing-field behavior for older saved reports. Render bars from their existing compatible frozen metrics when possible; do not regenerate missing Elo histories from today's data.
4. Define an evaluation artifact with schema version, model/code/data fingerprints, protocol version, evaluation period, sample counts, exclusions, metric definitions, aggregates, and provenance.
5. Define history-import manifests and preferences allowlists. Decide collision, capacity, and recovery rules before writing any target files.
6. Specify size bounds so enriched history remains within the existing 50-entry/50-MiB budget. Test worst-case long careers and Unicode metadata.

**Deliverable:** `docs/V0_6_DATA_CONTRACTS.md`, examples, and targeted fixtures. Preserve schema-1 readers unless a genuine incompatibility requires an explicit migration.

## M2 — Deliver fast initial evidence

### Step 5. Implement a lightweight reader

1. Add a small read-only adapter, provisionally `analyzer_quick_comparison.py`.
2. Reuse canonical identity resolution and dated coverage logic from `analyzer_catalog.py` and fight-history semantics from `analyzer_fight_history.py`.
3. Read only fields needed for the initial display. Avoid starting model training or constructing the complete advanced population history.
4. Profile repeated CSV scans. If necessary, build a compact derived index keyed by source content and schema; keep it optional, bounded, rebuildable, and separate from authoritative datasets.
5. Keep existing integrity checks. Do not replace content verification with modification-time assumptions to meet a speed target. Document whether initial evidence uses a validated startup index or request-time validation, and ensure it matches the context used for the final result.
6. Hold the existing operation lock across the request so app maintenance cannot change datasets between stages. Detect invalidated/external source changes according to the existing integrity policy.

### Step 6. Integrate staged delivery

1. Emit an initial-evidence event from the worker/public prediction orchestration before advanced engine preparation. Inspect the actual boundary in `ufc_matchup_analyzer.py`; avoid moving heavy work to the GUI thread.
2. Add the event to validated protocol/controller handling with the same job/request identity checks as existing comparison events.
3. Keep large payloads outside bounded progress lines when required; use validated job-local payload references consistent with the worker architecture. Do not simply increase event-size limits without evidence.
4. Display a clear initial comparison while the existing progress stages continue. Replace it with the advanced comparison for that same request, then add the prediction when ready.
5. Preserve the ability to inspect an older saved result during a running job. Do not let late initial or advanced events overwrite the user's chosen report.
6. Keep current exact-result reuse immediate; avoid replacing a complete reused report with an inferior initial stage.
7. On cancellation, keep the initial evidence explicitly partial. If advanced preparation already finished, retain the existing advanced partial-report behavior.

### Step 7. Verify behavior and latency

- Initial and final evidence agree on identities, eligibility, units, source context, and overlapping field definitions.
- Same-date/future bouts never enter historical evidence; zero and missing remain different.
- Predict and statistics-only flows, failure, cancellation, changed inputs, old-result viewing, and stale events behave correctly.
- Initial evidence is copyable/exportable with its partial label and is never added to completed history.
- Provisional UX target: initial evidence within 10 seconds after Analyze on the reference machine with a ready installation. Confirm feasibility after profiling; report actual distributions and any changed target before claiming success.
- Startup cost, final completion time, and memory do not hide a regression introduced to improve the headline initial timing.

**Primary areas:** `ufc_matchup_analyzer.py`, `analyzer_worker.py`, `analyzer_protocol.py`, `analyzer_controller.py`, `analyzer_gui.py`, `analyzer_catalog.py`, `analyzer_fight_history.py`, report formatting modules, and the new adapter.

## M3 — Optimize fresh calculations without changing results

### Step 8. Profile and rank bottlenecks

1. Add structured timings for imports, integrity validation, raw loading, dated state construction, advanced population traversal, fitting/calibration, cache serialization, and rendering.
2. Measure men and women independently. Recheck the previously expensive men's history traversal before selecting an optimization.
3. Rank candidates by measured time, peak memory, and semantic risk. Prefer eliminating duplicate scans, indexing immutable records, and sharing proved intermediate state within one request.
4. Keep model hyperparameters, seeds, priors, chronology, fold construction, and calculation definitions unchanged.

### Step 9. Implement one optimization at a time

1. Make app orchestration improvements here. For retained engine changes, verify the corresponding research source and implement/test the shared change there, then export through the established reviewed adapter workflow.
2. Prefer explicit prepared-context APIs over adding more runtime monkeypatching. Preserve v0.5 cache behavior while refactoring boundaries.
3. Bound memory and derived storage. Recalculate must bypass both saved-result and calculation-cache reads as it does today.
4. After each meaningful optimization, compare frozen outputs and raw features across the baseline matrix. Use the existing `1e-12` probability parity expectation; define any feature-specific tolerance explicitly rather than relaxing it after a failure.
5. Test fresh, cached, moved-folder, corrupted-cache, changed-dataset, changed-cutoff, and low-disk conditions. An optional cache failure must remain recoverable through computation.
6. Reproduce the exported engines and verify their manifests after any parent changes.

**Acceptance:** record at least three comparable timing runs and output parity. Set an improvement target after Step 8 identifies the available opportunity. A 25% reduction on an identified bottleneck may be a useful working target, but no fixed end-to-end speedup is promised before measurement. If optimization yields no reliable improvement, document that result and ship the useful initial view without claiming faster final prediction.

**Deliverables:** `tools/check_v06_performance.py`, before/after evidence, and reviewed source/export changes where needed.

## M4 — Add visual evidence

### Step 10. Build a compact comparison panel

1. Choose a small fixed set of compatible striking, grappling, and activity metrics per engine using existing definitions. Do not force men and women into identical metrics when semantics differ.
2. Draw paired horizontal bars with numeric labels and units. Both fighters share the same scale within a metric; unrelated metrics have separate scales.
3. Percentages use a 0–100% axis. For other nonnegative rates, show the axis and use a common zero baseline; handle signed metrics explicitly if included.
4. Show available denominators/sample counts beside the metric. State when an estimate is smoothed or prior-only. A recorded-fight count must not masquerade as the number of attempts supporting a rate.
5. Use neutral fighter colors; identify lower-is-better only where the metric definition supports it. Do not turn a bar difference into an inferred model explanation.
6. Render missing values as unavailable, not zero-length evidence of poor performance.

### Step 11. Add dated Elo trends

1. Extract the actual states used by each engine for the selected fighters. Decide and document whether each point is before or after the bout; use one explicit convention.
2. Keep only eligible bouts strictly before the selected fight date. Label overall versus selected-division series and make unsupported series unavailable.
3. Retain each engine's draw/NC, same-date, division, and starting-rating policies. Do not introduce a second Elo calculation just for a chart.
4. Include bout date, opponent, outcome, and rating in an accessible table. Avoid invented within-day chronology or interpolated values presented as observations.
5. Generate trends only when suitable prepared evidence is available; they must not delay the initial comparison.

### Step 12. Integrate reports and interactions

1. Use native Tk Canvas/ttk components where sufficient, avoiding an unnecessary browser dependency.
2. Link existing summary observations to the relevant chart/table evidence, retaining their current evidence thresholds and wording rules.
3. Save raw visual evidence with completed reports. Reopening a report uses that snapshot, including after updates or import.
4. Render the same evidence into standalone HTML using escaped SVG or simple HTML/CSS, with no external assets or network requirement. TXT retains equivalent numeric tables and support notes.
5. Provide keyboard-accessible detail views and labels that remain understandable without color or hover.
6. Verify narrow/wide windows, Small/Medium/Large text, real available display scaling, offline HTML, and browser printing. Record simulated scaling separately from physical OS scaling.

**Acceptance:** every plotted value, cutoff, sample count, and missing state matches its saved evidence and exported table. Older reports remain readable. Charts make no new prediction/reliability claims.

**Primary areas:** proposed `analyzer_visuals.py`, engine evidence adapters, `analyzer_summary.py`, `analyzer_reporting.py`, `analyzer_results.py`, `analyzer_gui.py`, and history compatibility tests.

## M5 — Evaluate the existing predictions

### Step 13. Freeze the research protocol

1. Verify the research parent and available data. Place model-evaluation code there first; the public app receives a reviewed report and any explicitly approved shared fixes.
2. Write the protocol before viewing evaluation results: eligible dates/bouts, chronological splits, model settings, metric definitions, comparison baselines, exclusions, and subgroup reporting rules.
3. Use chronological walk-forward evaluation grouped by event/date. No bout on the target event/date is training data for another evaluated bout that day.
4. Count one independent evaluation outcome per decisive bout. Keep mirrored A/B rows in the same group and never double-count them. Report draws/NCs separately and exclude them from binary scoring.
5. Generate features, priors, transformations, calibration, and ensemble weights using only eligible earlier information for each evaluation cutoff. Audit internal cross-validation as well as the outer split.
6. Separate a development period from a final chronological holdout. Freeze any protocol or model choices before opening the holdout results.
7. Document that later source/profile corrections may exist in the installed history: this is historical evaluation on a corrected snapshot, not a reconstruction of information actually published at the time.

### Step 14. Implement reproducible, resumable evaluation

1. Run the same public model settings and date semantics used by the app. Verify representative research/app parity before evaluating the full period.
2. Persist per-bout probabilities, outcomes, identities, cutoffs, model/data/code fingerprints, and calculation status.
3. Checkpoint after bounded event batches. Resume only when protocol and inputs match. Never silently skip failures or mix outputs from incompatible runs.
4. Compare against 50/50 and a simple training-only baseline, such as Elo-to-probability fitted on earlier data. Do not use winner-oriented ordering or a baseline fitted on the holdout.
5. Evaluate both engines separately. Add subgroup results for sparse history or divisions only with adequate counts; show unavailable/insufficient evidence otherwise.

### Step 15. Score and audit results

1. Report accuracy, Brier score, log loss, and a reliability diagram with declared probability bins and counts. State which direction represents improvement for each metric.
2. Define probability clipping for log loss in the protocol and disclose it. Preserve raw probabilities in research artifacts.
3. Include uncertainty estimates with event-aware grouping, and explain remaining dependencies such as repeated fighters. Do not use unqualified independent-row confidence intervals on mirrored data.
4. Reconcile evaluated, excluded, failed, and remaining bouts against the complete planned population. Failure accounting belongs in the report.
5. Manually inspect representative correct/incorrect forecasts, extremes, sparse-history cases, and any apparent leakage or model failure.
6. If a methodology defect appears, stop favorable performance claims, document it, and define a separate correction/evaluation cycle. Do not tune on the final holdout and keep calling it untouched.

### Step 16. Present a static, honest report in the app

1. Export a compact reviewed JSON artifact plus readable HTML/Markdown, with a content hash and full model/data/protocol identity.
2. Add a Model validation view showing evaluation dates, bout counts, metrics versus baselines, calibration, and limitations. Explain Brier score and calibration in plain language.
3. Clearly label whether the report covers the installed algorithm and evaluated dataset period. Dataset updates do not automatically validate a new snapshot; a historical report remains dated evidence.
4. Keep the view offline and lightweight. Do not run a large backtest on app launch or from an ordinary matchup request.
5. Do not convert historical calibration into a per-fight guarantee, betting-profitability claim, or invented confidence interval for an individual prediction.
6. Specify a follow-up prospective research ledger: save forecasts before events, preserve timestamps and fingerprints, and score later without rewriting forecasts. Local timestamps alone are not independent proof of publication time. The app's prunable recent-history list is not a complete prospective evaluation ledger.

**Acceptance:** reproducible per-bout results, explicit leakage audit, complete population accounting, and honest aggregate reporting. Model improvement is not a required result. An incomplete evaluation cannot be labelled validated or represented by fabricated placeholder metrics.

**Deliverables:** parent evaluation runner/protocol, reviewed public report artifact, proposed `analyzer_validation.py` reader/view, and `docs/MODEL_VALIDATION.md`.

## M6 — Preserve user work across portable upgrades

### Step 17. Implement read-only discovery and preview

1. Add Help → Import from previous installation. Accept a selected extracted app folder; do not recursively scan the user's drives.
2. Resolve the application layout and canonical source/target paths. Reject self-import, overlapping unsafe paths, and unsupported layouts with actionable messages.
3. Read only bounded JSON histories and approved preference fields. Never execute source code or deserialize old calculation artifacts.
4. Validate schema, integrity hashes, IDs, sizes, dates, and payload structure. A content hash detects changes; it does not establish that arbitrary imported content is trusted code.
5. Show valid, duplicate, conflicting, unsupported, corrupt, and over-budget counts before import. Invalid files do not silently disappear from the summary.
6. Compare exact record content for deduplication; do not discard different saved results merely because their requests match. An ID collision with different content is a visible conflict and is skipped by default.

### Step 18. Define a non-destructive merge

1. Preserve existing destination records. Let users select incoming entries that fit the remaining count/byte budget; do not prune current history automatically to make room.
2. Preserve imported IDs, payloads, original timestamps, and calculation fingerprints for accepted non-conflicting records. Record import provenance separately so frozen analysis contents stay unchanged.
3. Check imported results against current calculation context before reuse. A viewable imported result is not automatically valid for a fresh computation.
4. Offer an explicit preference-import choice with a small allowlist: text size, bounded window dimensions, collapsed inputs, and validated remembered selections. Preserve the destination history-storage preference unless the user explicitly chooses otherwise.
5. Validate remembered fighters through the current catalog before using them. Ignore obsolete absolute export directories or fall back to a usable location.
6. Exclude datasets, binaries, compute caches, operation locks, transaction journals, correction previews, logs, environments, and executable artifacts.

### Step 19. Stage, commit, recover, and report

1. Serialize destination writes with the app operation lock. Copy source JSON into private staging, validate the staged capture, and apply only the reviewed capture.
2. Detect changes to the selected source records between preview and capture; do not silently import a different set. Explain that the old app should be closed for a consistent import.
3. Revalidate target capacity/state immediately before commit. Use a manifest of newly created files, bounded preference backup, and a journal for interruption recovery.
4. Make restart recovery idempotent: finish or roll back only the import's own changes. Never erase unrelated destination history or source files.
5. A repeat import adds no duplicates. Cancellation before commit leaves the destination unchanged; commit/recovery state is truthful.
6. Show actual imported/skipped/conflicting counts and preference outcomes. Provide an undo for the latest import that only removes matching imported records and restores preferences when safe; report conflicts if those targets have since changed.

**Acceptance:** migration from representative v0.4 and v0.5 fixtures; Unicode/space paths; empty/full destination; disabled history; duplicates; conflicting IDs; oversized/corrupt/newer-schema records; read-only source; insufficient space; interrupted commit; repeat import; and offline open/compare/export afterward. Verify source hashes remain unchanged.

**Primary areas:** proposed `analyzer_migration.py`, `analyzer_history.py`, `analyzer_gui.py`, worker/recovery integration, and focused migration tests.

## M7 — Verify and package the complete release

### Step 20. Run integrated acceptance checks

1. Run the full data-equipped regression suite and setup/release audits after integration. Source-only CI remains a separate check and cannot establish prediction correctness.
2. Run actual native GUI → worker → engine predictions for both families, both fighter orders, historical cutoffs, sparse histories, and statistics-only mode.
3. Verify initial → advanced → prediction progression, cancellation/failure exports, current/old result navigation, and immutable saved reports.
4. Recheck v0.5 correction preview/apply/restore, cache reuse/clear/recalculate, and saved-version comparison workflows affected by shared changes.
5. Import real disposable older portable histories and preferences; reopen, compare, copy, and export the imported results offline.
6. Validate chart numerics and report provenance, not just screenshots. Also inspect actual native and HTML rendering at representative sizes.
7. Rerun controlled performance cases after integration to detect chart, evaluation-reader, or migration-related startup overhead.
8. Reproduce retained engine exports, verify manifests and all dataset hashes, and retain raw validation evidence outside deliverables.

### Step 21. Build a reviewable candidate

1. Update current README, changelog, model notes, quick start, maintenance/troubleshooting instructions, source/package allowlists, and applicable version fields.
2. Add `docs/V0_6_VERIFICATION.md` and machine-readable evidence that distinguish new measurements from inherited results.
3. Build clean portable/source archives using the verified runtime and existing packaging tools. Include the reviewed validation report if M5 passed.
4. Exclude personal histories, caches, transaction state, local benchmark outputs, raw evaluation forecasts, and development paths. Keep the existing dataset distribution policy.
5. Verify archive member inventory, hashes, CRCs, runtime dependencies, and fresh extraction. Launch the actual EXE from a space/Unicode path using its bundled runtime.
6. Verify offline predictions, charts, report viewing, import, clipboard, TXT, HTML, and a fresh-install first run.
7. Complete real clean Windows 10/11 and actual display-scale checks where environments are available; record unavailable checks explicitly. Simulated Tk scaling cannot replace them.
8. Keep unresolved dataset/platform limitations visible. Do not relabel an experimental candidate as stable because application tests passed.

### Step 22. Complete the applicable publication workflow

1. Review the finished source diff, candidate, release notes, and gate report as the concrete publication package.
2. When publication is requested, use the established draft-release workflow; verify source CI for the exact release revision and uploaded assets before publishing.
3. Download the published portable asset anonymously, verify its checksum, extract it, launch it, and run representative men/women predictions and the new workflows.
4. Record public-download evidence against that exact asset. Earlier local archive tests do not substitute for this step.

## Proposed work products and checkpoints

Create new modules only when they keep responsibilities clear; names below are provisional.

| Work product | Purpose |
| --- | --- |
| `docs/V0_6_DATA_CONTRACTS.md` | Initial/advanced states, chart evidence, evaluation and import contracts |
| `analyzer_quick_comparison.py` | Lightweight dated evidence |
| `analyzer_visuals.py` | Native visual rendering from frozen evidence |
| `analyzer_validation.py` | Read and present reviewed validation results |
| `analyzer_migration.py` | Validated staged history/preferences import |
| `tools/check_v06_performance.py` | Comparable performance/parity measurements |
| Focused tests plus portable workflow checks | State, date, numerical, export and recovery coverage |
| `docs/MODEL_VALIDATION.md` | Reviewed protocol, results, provenance and limitations |
| `docs/V0_6_VERIFICATION.md` | Final candidate evidence and remaining release gates |

At every milestone, save a concise checkpoint under `work/v06-validation/`: source revision, completed items, exact commands, input fingerprints, evidence paths, failures, and next action. Evaluation checkpoints also record completed/remaining event IDs. This allows a long run to resume without recomputing accepted work or mixing incompatible evidence.

Use small commits around contracts, initial evidence, each proved optimization, visuals/exports, validation integration, migration, and final verification. Run focused tests while developing; run the integrated matrix after the relevant pieces come together. Repeat expensive checks only after changes or failures that can affect their result.

## Scope controls and completion definition

No full-card scheduler, live odds feed, betting recommendations, new prediction algorithm, cloud account, web rewrite, or automatic executable updater is included. Native paired bars and Elo trends are sufficient; a general chart builder is unnecessary.

The largest uncertainties are fresh-run optimization, historical evaluation correctness/runtime, and crash-safe history migration. If a milestone proves larger than expected, make a documented scope decision rather than leaving a placeholder labelled complete. Evaluation must publish honest results even if the models do not outperform a baseline.

Implementation is complete when all four agreed improvements work in a freshly extracted portable candidate, the existing prediction/data workflows retain their required behavior, and the evidence supports every claimed speed, compatibility, and validation result. Public release completion additionally requires the applicable publication and downloaded-asset checks. Stable-release claims remain subject to the existing unresolved gates.
