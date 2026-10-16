# v0.8 implementation plan: performance and everyday usability

Prepared: 16 October 2026.

Status: implemented locally. Measurements and verification are recorded in `V0_8_BENCHMARK.md` and `V0_8_VERIFICATION.md`. Targets below remain the original planning targets; they are not claims of achieved performance.

Baseline: current local v0.7 application, including the UI polish recorded in `UI_POLISH_VERIFICATION.md`. Preserve the working tree's existing implemented and uncommitted changes.

## 1. Outcome and scope

Implement all five agreed improvements:

1. Faster startup, saved-report viewing, and statistics-only comparisons, with additional prediction optimizations where profiling justifies them.
2. Expandable recent-fight details using available recorded bout statistics.
3. Recent form versus UFC career performance, with explicit windows and support counts.
4. A guided Refresh and compare action built on existing saved-analysis comparisons.
5. A compact HTML report suitable for printing or saving as PDF through a browser.

Keep the existing Windows Tkinter/ttk application, single-matchup workflow, portable distribution, and current visual language. Prioritize responsive controls, readable evidence, predictable navigation and fewer repeated operations.

Prospective tracking, new model research, algorithm/calibration changes, full-card analysis, odds integration and automatic dataset downloads are outside this iteration. Do not expand or execute the prospective ledger as part of this plan.

Clean Windows 10/11 testing is deferred at the user's request because those environments are unavailable. It is not a prerequisite for implementing or handing off this local candidate. Actual alternative Windows display-scaling checks remain deferred; simulated Tk layouts and checks on the current computer must be labelled accurately. Keep existing release limitations documented without turning unavailable checks into repeated blockers.

Publication is outside this implementation plan. Finish with a verified local source/portable candidate and evidence of what was actually tested.

## 2. Existing building blocks and boundaries

| Area | Existing implementation to extend |
| --- | --- |
| Startup and background work | `analyzer_bootstrap.py`, `analyzer_worker.py`, `analyzer_controller.py`, `analyzer_protocol.py` |
| Analysis and initial evidence | `ufc_matchup_analyzer.py`, `analyzer_quick_comparison.py`, `analyzer_catalog.py` |
| Integrity and reuse | `analyzer_support.py`, `analyzer_history.py`, `analyzer_cache.py` |
| Recent bouts and full fight evidence | `analyzer_fight_history.py` |
| GUI, layout and themes | `analyzer_gui.py`, `analyzer_presentation.py`, `analyzer_widgets.py`, `analyzer_theme.py` |
| Saved-analysis differences | `analyzer_comparison.py` |
| Report formats and evidence | `analyzer_reporting.py`, `analyzer_results.py`, `analyzer_evidence.py`, `analyzer_visuals.py` |
| Migration and packaging | `analyzer_migration.py`, `tools/export_source.py`, `tools/package_release.py` |
| Existing verification | `tools/check_v07_performance.py`, `tools/check_ui_polish.py`, `tools/check_layout.py`, current regression suite |

Observed opportunities are hypotheses until measured: startup imports prediction/maintenance dependencies before dispatch; analysis validates and constructs catalogs before result lookup; recent-bout capture and full fight evidence read overlapping files; rendering builds several views from the same report. Do not claim these dominate latency without a profile.

Application-only presentation and read-only descriptive statistics can be implemented here. Any optimization touching engine feature preparation or model execution must be implemented and checked in the research parent first, then exported through the established adapters. Do not copy all parent files or alter model policy for speed.

Preserve the following throughout:

- Current probabilities, feature definitions, date/cutoff rules and model policies.
- Content-based cache validation, bounded storage, operation exclusion and transactional recovery.
- Immutable saved reports: rendering, refresh, export and imports never backfill an old report from current datasets.
- Explicit differences between initial, statistics-only, completed, failed and cancelled results.
- Existing data/evaluation provenance, missing-data semantics and retained limitations.
- User history-storage preferences and all existing keyboard shortcuts.

## 3. Delivery order

| Milestone | Work | Depends on | Completion evidence |
| --- | --- | --- | --- |
| M0 | Capture baseline and performance budgets | None | State inventory, fixtures, timings and profiles |
| M1 | Agree frozen data and interaction contracts | M0 | Schemas, formulas, state table and compatibility rules |
| M2 | Optimize startup and comparison paths | M0–M1 | Paired benchmarks and unchanged-result checks |
| M3 | Add recent-bout details | M1–M2 | Source reconciliation, native interaction and export checks |
| M4 | Add recent-versus-career view | M3 | Hand-calculated aggregate cases and UI checks |
| M5 | Add Refresh and compare | M1–M4 | Success, cancel, failure, identity and retention checks |
| M6 | Add compact report | M3–M5 | Offline HTML and inspected A4/Letter print output |
| M7 | Integrate, measure and package locally | M2–M6 | Regression, final timings, portable smoke and handoff |

At each milestone update a local `work/v0.8/RESUME-CHECKPOINT.md` with completed work, changed files, evidence paths, active process if any, unresolved issues and the next safe step. Store raw measurements and failed attempts alongside successful evidence so interrupted work can resume without repeating expensive runs.

## 4. M0 — Establish a trustworthy baseline

### Step 1: Preserve the current application

1. Record Git status, current version, relevant source hashes, dataset manifest, runtime/dependency versions and model policies.
2. Create an isolated reference copy from the actual working tree, including current v0.7/UI changes. HEAD alone is not the baseline because it predates those changes.
3. Use separate temporary history, preferences and caches for reference and candidate measurements. Do not benchmark by clearing the user's working installation.
4. Record the existing test commands and run the relevant baseline checks once. Distinguish pre-existing failures from regressions.

### Step 2: Capture representative cases

1. Include men and women, established fighters, limited-history/debut cases, an older fight date and a future date.
2. Freeze dates, fighter IDs, division, workers, inputs and dataset hashes. Record effective cutoffs and machine date so a later run does not silently change a future matchup's eligible data.
3. Include complete predictions, statistics-only results, older saved payloads, unavailable fields, draws/NCs, long accented names and reversed fighter order.
4. Include a 50-entry history near its existing byte limit, rather than checking only an empty history directory.
5. Capture the current Overview, Statistics, Charts, Recent fights, Report, history and comparison views at reproducible dimensions.

### Step 3: Measure the whole journey

1. Instrument process launch, first visible window, recovery completion, saved-history availability, catalog availability and readiness for computation separately.
2. Instrument validation/hashing, catalog parsing, initial evidence, advanced preparation, training, new evidence extraction, serialization/history save and UI rendering.
3. Record disk reads/bytes where practical, process-tree peak memory, cache hits/misses and time spent on the GUI thread.
4. Measure fresh computations with app caches bypassed, repeat requests with caches enabled, and opening an already saved report as distinct cases.
5. Use alternating reference/candidate runs, at least three pairs for expensive end-to-end requests and five startup samples. Record individual values, median and observed range; do not present a reliable p95 from three measurements.
6. Keep hardware, runtime, data, worker settings and workload constant. Record OS file-cache conditions as uncontrolled unless actually controlled; fresh app-cache runs are not cold-boot tests.

### Step 4: Freeze performance goals

These are engineering targets for the reference computer, not achieved results or promises for every PC. M0 must publish the measured baseline and lock the targets before optimization. If a target proves infeasible without changing semantics, document the evidence and the remaining gap rather than weakening correctness or silently lowering the target.

| Interaction | Proposed target |
| --- | --- |
| First usable window | Within 2 seconds of launch, with truthful initialization state |
| Open saved result after recovery/history readiness | Within 1 second for representative payloads |
| Startup to compute-ready | At least 25% lower median where baseline exceeds 5 seconds; preserve all required checks |
| Fresh advanced statistics-only result | At least 25% lower median for each model family where baseline exceeds 5 seconds |
| Initial evidence | No regression; target at most 5 seconds men / 2 seconds women on the idle reference computer |
| Already displayed matching comparison | Switch view within 150 ms without recomputation |
| Bout expansion and recent-window selection | Within 150 ms from frozen in-memory evidence |
| User feedback during work | Visible acknowledgement within 100 ms; no avoidable GUI callback blocking longer than 100 ms |
| Full fresh prediction | No reproducible median regression above 5% against v0.7; pursue improvements only from measured bottlenecks |
| Resource cost | Keep current cache/history caps; investigate peak-memory growth above 10% or any payload exceeding supported import limits |

Use an event-loop heartbeat during repeatable UI sessions to detect stalls; report the observed distribution and largest stalls, not only average speed. Isolated noise should trigger a bounded confirming measurement, not endless benchmark repetition.

Acceptance: reference artifacts, measurements, numerical outputs and test conditions are captured before application changes.

## 5. M1 — Define the contracts shared by all five improvements

### Step 5: Freeze normalized bout details

1. Introduce an optional versioned `bout_details` payload keyed by fighter ID and fight ID. Keep the existing `recent_fights` contract readable for old reports.
2. Capture bout date, event, opponent identity, division, result, method, round/time, duration, available fighter/opponent totals, missing-field reasons and source fingerprint.
3. Use the men's raw fight/stat tables and the women's existing repaired source fields. Document field mappings explicitly; never combine raw and repaired values opportunistically to manufacture a complete row.
4. Require unambiguous fighter/opponent pairing by stable identity within a bout. For women's rows, use profile identities and verified pairing; ambiguous name-only joins produce unavailable details.
5. Preserve zero as zero, missing as missing, and invalid as invalid. Validate nonnegative counts, landed <= attempted, finite values and positive duration where a duration-based rate is requested.
6. Freeze details for the displayed five recent bouts per fighter. Compute career/recent aggregates in the same source pass without duplicating every raw career row in the saved report.
7. Include all eligible recorded divisions and dates strictly before the selected fight date, matching the existing history view. Preserve and display any separate model training cutoff; do not present descriptive history as the training sample.

### Step 6: Freeze recent-form semantics

1. Add optional versioned `recent_form` evidence with Last 3, Last 5 and UFC career aggregates. Default to Last 5 versus UFC career, all recorded divisions.
2. Define UFC career as all eligible recorded UFC bouts before the selected date. It includes the selected recent window; label that overlap explicitly.
3. Select the most recent N recorded bouts first, then apply per-metric eligibility. Do not replace a recent bout with missing statistics using an older bout to make the sample look complete.
4. Count wins/losses/draws/NCs separately. Draw/NC statistics may contribute when valid; they are never converted into binary training outcomes.
5. Store metric IDs, semantic versions, units, numerator, denominator, eligible-bout counts, missing counts and covered dates, plus source/cutoff provenance.
6. Specify deterministic ordering by event date and fight ID where exact intraday order is unavailable. State that limitation for ties around a window boundary.
7. Calculate descriptive aggregates independently of prediction features. Do not feed these new summaries back into the engine.

### Step 7: Define report compatibility and UI states

1. Add bounded structural validation for new payload blocks and update import/export handling. Old reports remain readable with `Not recorded in this saved analysis`.
2. Ensure report-generation changes invalidate saved-result reuse when new evidence is required. Keep arithmetic-cache reuse separate only where its dependency contract proves compatibility.
3. Define states for initial evidence, details being prepared, details available, unavailable detail, statistics-only, complete, failed/cancelled and legacy reports.
4. Keep initial evidence fast: do not hold it until all new descriptive details are prepared. New fields may be unavailable in the initial preview; the completed result captures their final state.
5. Create a compact interaction specification for bout expansion, Last 3/Last 5 selection, refresh options and compact-export selection, including focus and busy-state behavior.

Acceptance: one documented schema/formula contract governs native views, saved results, comparisons and exports. No renderer reads current data to fill a saved result's gaps.

## 6. M2 — Improve startup and analysis speed

### Step 8: Separate startup readiness states

1. Render the lightweight window before expensive dependency imports or dataset scans.
2. Retain transaction/import recovery and the existing operation lock before accessing state affected by an interrupted write.
3. After recovery, allow reading/exporting validated saved reports while live-data checks continue. Mark compatibility as `Checking` until known; do not enable new computations prematurely.
4. Load lightweight history metadata first and deserialize a full report when selected. A cached history index must be rebuildable from original files after corruption or interrupted writes.
5. Explain initialization failures inline with an appropriate action. A dataset problem should not prevent opening a valid frozen report once state recovery is complete.

### Step 9: Remove measured duplicate work

1. Move operation-specific imports into their dispatch branches where profiling confirms a startup benefit.
2. Consolidate parsing used by catalog coverage, recent history, full fight fingerprints and new bout details into a request-local read-only source context where practical.
3. Reuse exact parsed rows and derived indexes within one validated snapshot. Avoid new database dependencies unless measurements demonstrate that the existing bounded structures cannot meet the goal.
4. Combine hashing/validation passes where the same bytes are currently scanned repeatedly, without reducing required validation coverage.
5. Preserve content-based correctness. File size/mtime alone must not authorize prediction/cache reuse; same-size edits with retained timestamps must still invalidate affected results.
6. Guard the relationship between validated bytes and parsed rows. A file changed during capture must cause retry/failure, not evidence assembled from mixed snapshots.
7. Treat cross-request caches as a second optimization only if request-local improvements are insufficient. Give each a content key, schema version, size limit, atomic writes and safe rebuild path.

### Step 10: Make the statistics-only route efficient

1. Trace and remove preparation that exists solely for fitting, calibration or prediction output from the compare route, while retaining every statistic the current advanced comparison promises.
2. Reuse compatible prepared history/features using the existing cache. Preserve Recalculate's existing bypass of both saved-result and computation-cache reads.
3. Keep the already displayed same-matchup fast path intact: switching to Statistics must not reload data, alter timestamps, clear the prediction or create another history entry.
4. If an engine bottleneck is involved, change the parent first and verify old/new raw metric and probability parity before exporting the optimization.
5. Do not remove advanced fields or relabel a partial preview as completed to meet a timing goal.

### Step 11: Reduce rendering cost

1. Build lightweight tab containers immediately; populate expensive charts and long tables when first opened.
2. Cache presentation models by frozen report identity and relevant display preference. Clear them when the displayed report changes; resizing alone should not reparse the report.
3. Batch table inserts and debounce resize/redraw work. Preserve selected rows, expanded bout and scroll position during harmless layout changes.
4. Keep computation and disk-heavy work outside GUI callbacks. Publish worker results through the existing controller and update widgets on the Tk thread.
5. Bound queued progress/render updates and discard stale events using request identity. Closing or changing a view must not apply an old callback to the new report.
6. Build complete exports from the payload, regardless of whether a lazy tab has ever been opened.

### Step 12: Verify the performance change

1. Run paired benchmarks with identical inputs and settings.
2. Compare categorical results exactly and numeric predictions/raw metrics with the established 1e-12 tolerance where applicable. Presentation timestamps and measured durations are expected to differ.
3. Exercise cache corruption, data modification, restore, cancelled work and opening history during computation.
4. Record measured gains per journey and model family, along with unresolved targets. Include all new evidence-generation work in final timings.

Acceptance: real speed gains are demonstrated without changed prediction semantics, missing comparison fields, weakened integrity or broken recovery.

## 7. M3 — Expand recent-fight details

### Step 13: Implement and reconcile the data adapter

1. Build one normalized adapter per model family using the M1 mappings.
2. Extract significant strikes landed/attempted, total strikes where reliable, knockdowns, takedowns landed/attempted, submission attempts, control time and duration. Include opponent values only where reliably paired.
3. Derive per-minute values only from validated elapsed duration. Prefer the recorded valid duration; never assume every round is five minutes when the source format differs.
4. Add opponent pre-bout Elo only when an existing dated engine state can be matched cheaply and unambiguously to that bout. Otherwise show unavailable. Never substitute current or post-bout Elo or retrain to fill the panel.
5. Compare a representative men's and women's bout directly against source rows, plus draw/NC, missing-stat and ambiguous-identity cases.

### Step 14: Add an inline detail panel

1. Retain the two fighter lists in Recent fights. Add a clear `Show bout details` action for the selected row; support Enter and double-click as alternatives.
2. Expand a panel beneath that fighter's list, with date/opponent/result followed by aligned fighter/opponent statistics and units.
3. Keep one selected detail panel per fighter, readable side by side at wide sizes and stacked at narrow sizes.
4. Display recorded source limitations near affected fields. Do not use an empty bar for missing data or color alone to signal a result.
5. Provide a collapse action and return focus to the selected bout. Expanding, collapsing and switching tabs preserve sensible scroll position.
6. Opening a panel reads only the frozen payload and must not trigger fetching, training or a fresh analysis.

### Step 15: Carry details through saved results and full exports

1. Save the captured detail block with completed predictions and completed statistics-only reports.
2. Include it in detailed TXT and HTML exports; browser HTML may use expandable sections on screen, but printing must not silently hide requested full-report details.
3. Preserve old-report behavior and a clear route to Refresh and compare when recalculation is needed to capture detail.
4. Verify saved/reopened/imported details are byte-equivalent and source corrections do not rewrite them.

Acceptance: selecting a recent bout reveals useful available statistics within the interaction budget, works by keyboard, and matches the saved/exported evidence.

## 8. M4 — Compare recent form with UFC career performance

### Step 16: Implement explicit descriptive formulas

| Metric | Aggregation rule | Support shown |
| --- | --- | --- |
| Significant strikes landed/absorbed per minute | Sum eligible landed/absorbed strikes divided by the matching sum of eligible fight minutes | Bouts and minutes |
| Significant-strike accuracy | Sum landed / sum attempted across rows with both fields valid | Bouts and attempts |
| Takedowns per 15 minutes | 15 × sum takedowns landed / matching eligible minutes | Bouts and minutes |
| Takedown accuracy | Sum landed / sum attempted where both fields are valid | Bouts and attempts |
| Takedown defense | 1 − sum opponent landed / sum opponent attempted using paired valid values | Bouts and opponent attempts |
| Control share | Sum valid control seconds / matching eligible elapsed seconds | Bouts and elapsed time |
| Recorded results | Separate W/L/D/NC counts in the selected window | Total recorded bouts |

1. Use pooled totals, not an unweighted average of per-fight percentages. Every numerator and denominator must come from the same eligible subset.
2. Zero attempts yields unavailable accuracy/defense with `0 recorded attempts`; positive attempts with zero success yields a genuine 0%. Do not apply model priors to descriptive aggregates.
3. Exclude invalid/unknown durations from time-based metrics only; keep their valid count-based evidence where appropriate and show per-metric exclusions.
4. Preserve invalid values as explicit unavailable data, rather than silently clipping impossible counts or control durations.
5. Display the actual window size when fewer than three/five bouts exist. Keep lone-bout values descriptive and avoid directional narrative; if recent equals career, state that there is no separate earlier-history comparison.
6. Show opponent context as recorded opponent names and available dated pre-bout ratings with coverage. Do not compare a partially covered average rating as if it represented every opponent, or mix overall and division Elo.

### Step 17: Present the comparison without crowding Overview

1. Add a Recent form section within the existing Statistics tab, reachable from a small Overview link. Keep the five-tab navigation.
2. Provide a Last 3 / Last 5 selector, default Last 5, and a fixed UFC career reference. Precompute both windows so switching is immediate and does not retrain.
3. Show each fighter's recent value, career value, difference and support count in an aligned table. Use percentage points for percentage differences.
4. Retain labels and values as the primary evidence. Add restrained paired bars only if they improve scanning; bars use comparable axes and cannot hide missing values.
5. Label the all-divisions scope, cutoff, dates and career overlap prominently enough to interpret the comparison.
6. Use neutral wording such as `Higher recorded output in the last five bouts`. Avoid `improving`, `declining`, causal explanations or new confidence grades.
7. Apply the current Small/Medium/Large text setting and keyboard navigation to the new controls.

### Step 18: Verify calculations and preservation

1. Check hand-calculated cases with unequal bout durations and attempt counts, missing denominators, zero attempts, one/fewer-than-N bouts and draws/NCs.
2. Test boundaries at the selected fight date and same-day ordering, duplicate rows and reversed fighter order.
3. Validate both family adapters against actual source examples. Confirm the new descriptive values do not alter model inputs or predictions.
4. Store both recent windows and career data; full TXT/HTML exports include their definitions and support. The compact export uses an explicitly selected window.
5. Verify saved reports retain the original values after datasets are updated or restored.

Acceptance: the user can distinguish recent from career performance and see exactly how much recorded data supports each value.

## 9. M5 — Guided Refresh and compare

### Step 19: Add the action and define its meaning

1. Add `Refresh and compare` to Recent analyses for one selected entry and to the displayed saved-report actions using the semantic command registry.
2. Show a small setup dialog identifying the original report and its generation time. Default to the same fighters, order, division, fight date and explicit as-of setting using the installed datasets/current app.
3. Offer `Use today's matchup date` as an explicit alternative with the changed date visible before starting. Revalidate an old explicit as-of setting against any new date.
4. Explain that refresh uses installed data. Dataset download remains a separate existing maintenance action and is never triggered silently.
5. Retain the original operation: a statistics-only report refreshes as statistics-only; a prediction refreshes as a prediction. Do not silently introduce training.
6. Re-resolve stable IDs and reject ambiguous/missing identities with an actionable message. Legacy records without enough request context require explicit reconstruction rather than guessed settings.

### Step 20: Run one tracked refresh

1. Capture the original report/context into an immutable in-memory comparison reference before starting.
2. Generate a new result and generation timestamp, bypassing saved-result lookup. Allow content-compatible computation caches for speed. Keep full `Recalculate` as the existing action that also bypasses computation caches.
3. Implement saved-result bypass separately from `force_recalculate` if needed; do not disable cache validation or silently change current Recalculate behavior.
4. Retain the original on screen with progress. On successful completion open the before/after comparison if the user is still following this refresh; if they navigated elsewhere, present `Open comparison` without stealing focus.
5. A cancelled or failed refresh keeps the original, preserves clearly labelled partial evidence under current rules, and creates no completed comparison/history entry.
6. Track operation identity so unrelated completions, repeated clicks or late worker events cannot open the wrong comparison.

### Step 21: Protect the original and respect history preferences

1. Prevent automatic history pruning from deleting the comparison's source report during this operation. Audit the existing pruning path before saving the new result.
2. If history is disabled, compare transiently without silently enabling storage. If storage is full, retain the original and use a transient new result when a safe bounded save is impossible.
3. Report a failed history save separately from a successful computation. The user must still be able to inspect/export the completed comparison.
4. Do not permanently pin reports or increase the existing history limits as a side effect. Any temporary reservation must be cleaned up after completion/recovery.
5. Keep the result available even if the source history item is explicitly deleted later; the active comparison uses its captured original rather than rereading a mutable file.

### Step 22: Improve the comparison presentation

1. Reuse `compare_entries` identity alignment and semantic checks.
2. Put Before/After probabilities and changes in percentage points first when both are predictions; omit that section for statistics-only results.
3. Follow with changed inputs/data/model context, newly eligible or corrected bouts, and compatible metric/recent-form differences.
4. Identify eligibility changes from a changed date separately from source-record corrections. Never infer deletion simply because a bout left the last-five window.
5. Keep a clear `No material result changes` state when recomputation is equal, even though generation time changed.
6. Link to each complete report and preserve existing comparison TXT/HTML export. Do not attribute a probability shift to one factor when several inputs changed.

Acceptance: one guided action produces a trustworthy before/after comparison without changing the original date implicitly, overwriting history, guessing identity or leaving stale completion state.

## 10. M6 — Compact HTML and print report

### Step 23: Define the compact content budget

1. Add `Compact matchup summary (.html)` as a distinct Save report format. Preserve detailed TXT/HTML and existing Copy report behavior.
2. Include fighter names, division, fight date, result mode, original generation time and dataset date.
3. Include probabilities only for completed predictions, plus the captured reliability status and essential evidence limitations.
4. Include six consistently selected key comparisons, a compact Last 3/Last 5 versus career section and three most recent recorded bouts per fighter. Label the three-bout export subset; the app still shows five.
5. Choose the recent-form window explicitly in export options, default Last 5, and print that choice. Do not let a hidden UI selection change exported meaning.
6. Include model/version, cutoff and a concise methodology/limitations footer. Omit unavailable decorative content before reducing essential context.
7. Old reports can export the information they contain with unavailable sections labelled. Initial/failed/cancelled exports must visibly identify their state and omit unsupported probabilities.

### Step 24: Implement a self-contained template

1. Add a focused formatter such as `analyzer_compact_report.py` using the same frozen evidence and metric formatters as the UI.
2. Use embedded CSS, local system fonts and inline graphics only. No CDN assets, network requests, tracking, scripts or embedded machine paths.
3. Escape all user/source text and validate any links. Long names must wrap safely.
4. Use responsive screen layout, print styles, page margins and controlled row/section breaks. Keep numbers legible in grayscale and independent of colored background printing.
5. Target one page for normal reports on A4 and US Letter at 100% scale with documented browser header/footer settings. For unusually long names or necessary limitations, allow an explicit second page rather than clipping content or shrinking it to unreadable text.
6. Keep print generation outside model computation; use browser Print/Save as PDF without adding a bundled PDF engine.

### Step 25: Verify real exported output

1. Open exported HTML offline and inspect men, women, statistics-only, sparse-history and legacy fixtures.
2. Print representative cases to PDF using the available browser and inspect rendered pages for page count, clipping, wrapping, units and footer readability on A4 and Letter.
3. Check that no hidden/collapsed screen section disappears unexpectedly in print and that all displayed numbers match the frozen report.
4. Exercise Unicode filenames, save cancellation, declined overwrite and unwritable destinations through the existing save workflow.
5. Keep screenshots/print samples as evidence. A valid HTML string alone does not complete layout verification.

Acceptance: a readable, offline compact report can be saved and printed with accurate values and essential limitations; standard fixtures fit one page under documented settings.

## 11. M7 — Final integration, measurement and local delivery

### Step 26: Verify the complete user journeys

1. Launch, open an older report during data checks, start a new matchup, inspect initial evidence, then browse complete results.
2. Expand recent bouts, switch Last 3/Last 5, change text size, resize the window, switch tabs and export without changing the frozen report.
3. Refresh a saved prediction and a saved statistics-only report using both same-date and explicitly changed-date modes.
4. Exercise cancellation/failure, concurrent history viewing, 50-entry capacity, disabled history, legacy schema, duplicate names and invalid/missing details.
5. Apply a controlled data change in an isolated copy, verify cache invalidation and old-report immutability, then restore and check recovery behavior.
6. Verify full exports include lazy views that were never opened and compact exports preserve their declared subset/window.

### Step 27: Run proportionate regression and usability checks

1. Extend existing tests for new data contracts, aggregate arithmetic, request/caching semantics, refresh state and history retention. Add tests for meaningful failure cases rather than mirroring widget construction.
2. Run the full applicable native/data-equipped suite once the integrated implementation is stable; investigate failures and rerun affected checks after fixes.
3. Run dataset-free source checks with the documented source-only setting and report expected skips accurately.
4. Exercise keyboard-only flows, visible focus, readable status/error messages, narrow supported layouts, long names and Small/Medium/Large text.
5. Use the existing simulated Tk scaling matrix on the available machine, including 100/125/150/200%. Record actual requested/resulting dimensions and native DPI. Do not call these clean OS or real alternative-DPI tests.
6. Use available native accessibility inspection where possible; keyboard and contrast checks alone must not be represented as complete screen-reader certification.

### Step 28: Confirm final performance

1. Repeat the locked M0 benchmark matrix with all five features enabled, on the same data/runtime/hardware and controlled app-cache settings.
2. Report reference/candidate individual timings, medians, ranges, initial-evidence times, rendering stalls, process-tree memory and payload/cache sizes.
3. Inspect any material regression attributable to new evidence extraction, rendering or history loading. Fix within scope and rerun affected cases.
4. Preserve parity evidence and clearly mark targets met, missed or not measurable. Do not report an earlier intermediate benchmark as the final candidate's performance.

### Step 29: Package a local candidate

1. Update version metadata, source/package allowlists, README, changelog, quick start and upgrade guidance for the final behavior.
2. Produce `V0_8_DATA_CONTRACTS.md`, `V0_8_BENCHMARK.md`, `V0_8_VERIFICATION.md` and `V0_8_UPGRADE.md` from actual implementation/evidence.
3. Build separate source and Windows portable candidates, retaining all 15 matching datasets inside the portable and excluding runtime state/research artifacts from public source.
4. Verify archive members/checksums and source/runtime/data parity. Extract to a fresh writable folder with spaces/Unicode on the existing machine and run the EXE, both model-family workflows, imports, refresh and exports offline.
5. Record this as a fresh-folder portable test on the current computer. Explicitly list clean Windows 10/11 and real alternative-DPI checks as deferred, without blocking the local handoff.
6. Deliver artifact paths, benchmark evidence, known limitations and concise usage instructions. Leave publication for a separate user request.

## 12. Completion criteria

- All five features work in the native app and their intended export/history paths.
- Startup/comparison changes have measured before/after evidence; speed claims distinguish fresh computation, cache reuse and saved-report opening.
- Current model arithmetic and established cutoff behavior remain unchanged within the existing parity contract.
- Bout details and recent-form metrics are source-reconciled, support-labelled, frozen and unavailable where evidence is missing.
- Refresh preserves the original, exposes date/context changes and handles failure/cancellation/history capacity correctly.
- Compact HTML works offline and has inspected print output; full reports retain all their information.
- The relevant regression suite and available-machine usability/portable checks pass, with any remaining performance targets or environmental limits disclosed.
- No prospective tracking or unavailable clean Windows testing is required to finish this scoped local iteration.

## 13. Implementation references

The Tkinter event loop requires callbacks to finish promptly; use the existing background-operation architecture and return widget updates to the GUI thread. See [Python 3.14 Tkinter threading model](https://docs.python.org/3.14/library/tkinter.html#threading-model).

Use separate screen/print CSS and page rules for the compact report, and verify the actual browser output. See [MDN printing guidance](https://developer.mozilla.org/en-US/docs/Web/CSS/Guides/Media_queries/Printing).
