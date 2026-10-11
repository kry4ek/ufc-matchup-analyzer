# Next version implementation plan

Proposed release: v0.4.0 experimental Windows release
Prepared: 11 October 2026
Status: implemented and verified; source pushed to GitHub; three-platform source CI passed

## Implementation evidence

The four improvements are implemented in v0.4.0. Fresh verification passed 128 native regression tests, a mixed decisive/draw/NC update and full rebuild for both targets, a real 22-men/4-women update with repeat and restore, the actual maintenance error dialog's Retry action, offline predictions for both models and a historical case, and 10,800 feature-parity comparisons. Native comparisons, cancelled previews, TXT/HTML exports, recent-fights layouts and fresh portable launch also pass.

The owner subsequently requested an update to the GitHub source repository and explicitly authorized publication of the v0.4.0 portable app. This remains an experimental prerelease and does not replace an existing installation automatically. See [release verification](../RELEASE_VERIFICATION.md), [structured evidence](../verification_evidence.json) and [changes](CHANGELOG.md) for completed checks and scope. The approved design and acceptance criteria below are retained for reference.

## Release outcome

Deliver four improvements to the existing single-matchup desktop app:

1. Consistent acceptance of completed draws and no-contests in both dataset updaters.
2. Clear maintenance errors with useful actions and durable diagnostics.
3. Measured update progress and a browsable summary of captured fights.
4. Each fighter's five most recent eligible UFC bouts, included in the displayed and saved report.

The first three improve the Update datasets workflow. The fourth makes the statistics easier to understand using the same local data and historical date rules as the comparison.

Performance optimization and automatic rechecking of older events are separate follow-up projects. This release retains the current model versions, calibration, feature definitions, and engine-specific Elo policies. New valid source data can legitimately change future predictions. It continues to use the existing local portable installation, transaction backups, and single-operation lock.

## Verified starting point

- The current source version is 0.3.0. Recent analyses, date-aware coverage, comparison previews, cancellation, TXT/HTML exports, and update backups already exist.
- The women's updater has the local draw/NC repair from this chat: two source-stat rows are retained, while newly appended binary training rows exclude these outcomes.
- That repair passed 107 tests, a source audit, all 15 installed-dataset checks, a real update, and a fresh prediction. These are baseline results, not evidence for the proposed release.
- The men's updater still rejects result pairs without one winner and one loser at both metadata and parsed-fight checks. Its new-row audit also assumes binary outcomes.
- Maintenance sends broad stage messages to an indeterminate progress bar. The child process runner writes human-readable logs but does not relay detailed child progress.
- Source-audit errors can embed a staging path. The transaction later copies audits to a retained directory and removes staging, leaving that error path unusable.
- The fighter catalogue currently indexes dates and divisions for coverage; it does not provide a complete recent-bout list.
- Saved analyses contain immutable report payloads. The new list must be captured with the analysis and reused with it.

## 1. Completed result handling

### Intended behavior

Both update routes recognize the same logical outcome categories while retaining their existing CSV schemas:

| Source result after validated normalization | Capture behavior | Binary target |
|---|---|---|
| One W and one L | Retain both fighters and the decisive fight | 1 and 0, matching the winner |
| D and D | Retain the completed draw and both fighters' statistics | Missing for both fighters |
| NC/N/C on both sides | Retain the completed no-contest and both fighters' statistics | Missing for both fighters |
| Blank, unsupported, contradictory, or incomplete result | Block installation and identify the affected bout | Never manufactured |

Keep the men's existing narrowly constrained normalization for source pages with an omitted opposing loss marker. Test its prerequisites explicitly. Draw/NC markers must never trigger winner/loser inference.

Keep men's `no_contest` and women's `nc` storage values where required by existing readers; map them to a common display/audit category. A broad migration of historical CSV values is unnecessary.

### Implementation tasks

1. Add matching result-contract fixtures for both updater adapters, including the repaired women's behavior.
2. Update men's `validate_completed_fight_meta` to accept consistent completed non-binary pairs after date and identity checks.
3. Update the post-parse checks in men's `main`: verify agreement between source markers, parsed fight outcome, fighter outcomes, winner/loser IDs, and targets. A non-binary fight has no winner or loser ID.
4. Extend `audit_new_rows_for_apply` to accept missing targets only for a fully validated draw/NC pair. Continue blocking missing targets on W/L rows, numeric targets on draw/NC rows, duplicate IDs, future dates, and malformed fighter pairs.
5. Trace the full men's rebuild chain and validate raw-fight/stat coverage separately from binary training eligibility. Retained raw draw/NC rows should not be reported as missing binary training examples.
6. Verify the existing feature builders retain their established treatment of historical draws/NCs and that binary fitting excludes missing labels. Preserve same-date leakage protections.
7. Add outcome and training-eligibility fields to fight audit records for both routes, so the completion summary can explain captured versus training-eligible bouts.
8. Update the reproducible export/adaptation workflow and exported hashes so a later source export cannot erase this fix or the existing women's repair.

The staged engines currently receive copies of their own directories. Any shared result helper must be explicitly available in staged and standalone CLI execution; do not introduce an implicit dependency on an un-copied application module. Prefer small engine adapters with shared contract tests unless a shared module makes this dependency clear.

### Acceptance criteria

- Men's and women's fixtures containing decisive fights, a draw, and a no-contest complete capture and rebuild successfully.
- Each accepted fight has exactly two distinct fighter-stat rows with consistent identities and results.
- Draw/NC rows have no invented winner, loser, or binary target and never reach binary model fitting as labeled examples.
- Conflicting markers, unknown results, future dates, missing fighters, and failed source fetches still block the whole transaction.
- Repeating a completed update adds no duplicate fights or unnecessary rebuilds.
- Existing-data prediction parity holds when only presentation/protocol code changes. Tests that add new valid fights assert the expected data changes and cutoff rules rather than demanding unchanged future predictions.

Primary files: `mens_ufc_model/update_ufc_mens_dataset_incremental.py`, `womens_ufc_model/update_ufc_womens_dataset_incremental.py`, `mens_ufc_model/src/data/ingest_ufcstats.py`, the men's feature/validation modules where required, `analyzer_maintenance.py`, `tests/test_safety.py`, and the source export tools.

## 2. Maintenance errors and recovery actions

### Intended interface

Replace a raw exception string and long filesystem path with a compact dialog containing:

- A specific title, such as **Could not download fight details** or **A fight result needs checking**.
- The affected event and fighters when known.
- A plain-language reason and the appropriate next step.
- An accurate statement of installation state, derived from the transaction journal.
- **Retry**, when appropriate; **View details**; **Copy diagnostics**; and **Close**.

Example for a failed download:

> Could not download fight details
> Event: [event name]
> Fight: [Fighter A] vs [Fighter B]
> Check your internet connection and try again.
> Your installed datasets are unchanged.

The last sentence is shown only when the journal confirms there were no installed changes or rollback completed. An interrupted commit or failed recovery must show the recovery state instead.

### Structured error contract

Introduce a maintenance-specific error payload with stable fields:

| Field | Purpose |
|---|---|
| `code` | Machine-readable classification |
| `title`, `message`, `next_step` | User-facing explanation |
| `operation`, `stage`, `target` | Update/rebuild and men/women context |
| `transaction_id`, `event_id`, `fight_id` | Diagnostic identity when available |
| `event_name`, `fighter_a`, `fighter_b` | Readable bout context |
| `retryable` | Whether a manual retry is appropriate |
| `installation_state` | Unchanged, rolled back, committed, or recovery required |
| `diagnostics_path` | Existing retained log or audit location |

Classify network/fetch failures, invalid source results, malformed source content, data validation failures, insufficient disk space, operation-lock conflicts, cancellation, subprocess failures, and recovery failures. Preserve the full exception traceback in the diagnostic log. Unknown exceptions receive a useful fallback and remain visible as failures.

### Implementation tasks

1. Add a small typed-error module, provisionally `analyzer_errors.py`, and include it in the package allowlist.
2. Build typed errors at the point where source or validation context is available. Do not infer failure categories by matching translated display strings.
3. Preserve a reference relative to the engine audit root. After audits are copied, resolve it against `transactions/<id>/audits/<target>/...` before sending the terminal worker event.
4. Always retain a usable transaction-level log fallback if audit export fails or a referenced file is missing. Preserve the original failure in diagnostics even if cleanup encounters a second failure.
5. Extend `analyzer_worker.py` to serialize the structured error alongside existing job/request identity fields. Keep a fallback for older or synthetic worker error events.
6. Add a dedicated maintenance error dialog in `analyzer_gui.py`. Include selectable details and diagnostic-copy support; reuse established process/clipboard helpers.
7. Manual Retry recreates the original maintenance request with a new job and transaction after the failed process has ended and locks are released. Limit Retry to appropriate transient failures. Invalid source results lead to explanation/details rather than an immediate retry loop.
8. Copy diagnostics includes app version, error code, transaction, stage, relevant source IDs, and a bounded sanitized excerpt. Redact local account paths by default; do not copy credentials or unrelated environment values.

### Acceptance criteria

- Every View details action opens a real retained file or directory after staging has been removed.
- The affected fight is displayed for bout-specific failures; missing context has a readable fallback.
- Retry never overlaps the failed worker or bypasses startup recovery.
- Cancellation remains a normal cancelled state rather than an alarming error dialog.
- Errors during maintenance preserve the currently displayed analysis and its Copy/Save behavior.
- Diagnostic text can be selected and copied; keyboard focus and Escape behave correctly.

Primary files: new `analyzer_errors.py`, `analyzer_maintenance.py`, `analyzer_runtime.py`, `analyzer_worker.py`, `analyzer_controller.py`, `analyzer_gui.py`, and GUI/protocol/safety tests.

## 3. Update progress and completion details

### Intended interface

Show real units of work when a denominator is known:

- **Men: checking event 2 of 2 — [event name]**
- **Inspecting bout 8 of 12 in this event**
- **Men: rebuilding features — step 3 of 4**
- **Validating historical cutoffs — 4,200 of 7,840 fights checked**
- **Installing validated datasets**

The numbers above are examples, not hardcoded totals. Keep elapsed time visible. A progress bar represents the named current phase; it must not imply an overall percentage when phase costs differ or totals are unknown. During unmeasured work, use an activity indicator and label the current operation accurately.

### Progress contract and transport

Extend the existing structured event mechanism with optional fields: `target`, `phase`, `step_index`, `step_count`, `completed`, `total`, `unit`, `detail`, and `cancellable`.

- Child updaters, feature builders, and validators emit JSON events to a per-child event file through an explicit configured path.
- Extend `run_logged_process` to relay complete event records through the maintenance callback while retaining its cancellation, timeout, logging, and process-tree behavior.
- Keep machine events separate from stdout/stderr. Human-readable logs remain useful diagnostics and are never parsed for progress.
- The worker supplies the authoritative job/request identity. Child events cannot override terminal status or make the commit phase cancellable.
- Handle partial UTF-8 writes, unknown optional fields, and final records emitted just before child exit. Bound event size and emission frequency; use a shared reader if it avoids duplicating the controller's existing line-framing logic.
- Throttle loop updates to a modest frequency, such as at most four per second, with guaranteed phase-start and phase-completion events. A periodic liveness indication must not be presented as completed work.

### Completion summary

Extend the current Dataset status and update details view with a **View updated fights** action. Store a compact summary in maintenance status and a detailed list with the transaction audits.

For each target, show events inspected, newly captured bouts, decisive bouts, draws, no-contests, binary training rows added, data-through date, and the final transaction state. The list shows date, event, fighters, outcome, and training eligibility. Count fights separately from the two fighter rows and two mirrored training rows.

Only successful installation produces an **Update complete** summary. Dry-runs describe proposed changes. Failed or cancelled transactions describe attempted work without claiming it was installed. An unchanged run records a successful check and reports **Already up to date**.

Retain detailed successful-update information for the same lifetime as its recoverable backup. If an older audit has been pruned, the status view must explain that its detailed list is unavailable instead of offering a broken link.

### Implementation tasks

1. Define event validation and optional-field fallback in `analyzer_protocol.py` and runtime/controller handling.
2. Instrument event/bout loops in both updaters using actual discovered counts, clearly distinguishing all inspected bouts from target-category captures.
3. Emit numbered steps around existing rebuild subprocesses. Add counters at useful checkpoints in long-running build/validation loops, without changing calculations or traversal order.
4. Add current-phase progress rendering to the GUI, resetting the bar when the phase or unit changes.
5. Build the per-fight summary from structured audit records; persist it through the existing transaction/status flow.
6. Refresh freshness, catalogue coverage, update details, and backup availability after a successful commit, preserving displayed reports.

### Acceptance criteria

- Counters use the correct unit and denominator and reach completion only when their phase actually finishes.
- Unknown totals show no fabricated percentage or ETA.
- Men/women phases, retries, cancellation, and no-change runs reset the display correctly.
- Malformed progress cannot be mistaken for a successful audit or terminal result.
- Window interaction and cancellation remain responsive during downloads, builds, and audits.
- Commit remains non-cancellable and retains the current crash-recovery guarantees.
- A test update with decisive fights plus a draw/NC has summary totals that reconcile exactly with the retained data and binary training additions.

Primary files: `analyzer_protocol.py`, `analyzer_runtime.py`, `analyzer_maintenance.py`, both updaters, instrumented feature/validation scripts, `analyzer_worker.py`, `analyzer_controller.py`, `analyzer_gui.py`, and maintenance integration tests.

## 4. Recent-fights panel

### Intended interface

Add a **Recent fights** tab alongside Overview, Fighter comparison, and Full report. It contains one compact table per fighter and the label:

> Last five recorded UFC bouts before [selected fight date]

Use side-by-side tables when space permits and stack them vertically at narrower widths or larger text sizes. Keep the content within the existing resizable layout. This separate tab avoids crowding the Overview or changing the metric-filter workflow.

| Column | Display |
|---|---|
| Date | Event date |
| Opponent | Recorded opponent name |
| Result | Win, Loss, Draw, or No contest |
| Division | Division recorded for that bout |
| Method | Recorded method; N/A when unavailable |

Event name, round, and time can appear in a selected-row details area. Use text labels as well as any result colors. Show all eligible divisions; the displayed division makes moves between weight classes visible. Fewer than five bouts displays the available rows, and zero eligible history gets an explicit empty-state message.

### Data and date rules

1. Resolve the same canonical fighter identities used by the analysis. Men use fighter IDs. Women preserve the existing ambiguity rejection and use the unique validated identity; do not guess between identical names.
2. Read men's raw fights plus fighter/stat records for opponent names and result mapping. Read women's repaired fighter-fight statistics for the equivalent fields.
3. Deduplicate by fight ID and fighter identity before selecting five rows. Mirrored training records are not a history source.
4. Require `event_date < fight_date`, matching the comparison's history rule. Include every qualifying bout category, including draws/NCs.
5. Sort descending by date with a deterministic fight-ID tie-breaker. Same-day ordering is not claimed to be the actual chronological bout order.
6. The men's optional earlier training cutoff remains distinct from the date used for displayed fighter history; label these dates separately in reports where applicable.
7. Historical results describe the installed source snapshot. Do not claim that later source corrections reproduce what was publicly known on the historical date.

### Payload and integration design

Add an optional `recent_fights` object to comparison previews and final result payloads. Include its schema version, history cutoff, and ordered `fighter_a`/`fighter_b` arrays. Each row contains `fight_id`, `event_date`, `event_name`, `opponent`, `opponent_id` where available, `division`, `result`, `method`, `round`, and `time`.

Create a small read-only adapter, provisionally `analyzer_fight_history.py`. Build the list under the same operation lock and validated dataset state as the analysis. Reuse already-loaded catalogue/raw data where practical and avoid rereading large files on the Tk thread. The lightweight coverage index can remain optimized for suggestions.

Attach the same captured list to the early comparison and completed prediction. It stays available for a failed or cancelled prediction that already produced a comparison. Statistics-only results receive the same list without fitting a model.

Save the list inside the existing immutable history payload. Later dataset updates must not rewrite the list for an old analysis. Older saved payloads without the field remain readable and show **Recent fights were not saved with this analysis. Recalculate to include them.** Do not silently populate old reports from today's data.

Add the same ordered lists to the complete clipboard/TXT/HTML reports through shared formatting helpers. Missing historical fields display consistently across formats. New calculations use the existing code/data/version fingerprint rules, so a payload produced before this feature cannot be reused as a fully current result by accident.

### Acceptance criteria

- At most five correct, unique bouts per fighter, newest dates first, with result labels from that fighter's perspective.
- Bouts on or after the selected date never appear, including a historical target bout.
- Draws/NCs appear in recent history even though they are excluded from binary target fitting.
- Swapping fighters swaps lists correctly; changing inputs does not relabel an already displayed saved result.
- Duplicate names, aliases, missing opponent metadata, zero history, and cross-division history have deterministic behavior.
- Preview, completed prediction, statistics-only result, saved history, clipboard, TXT, and HTML agree.
- Opening an older saved report does not cause an online fetch or mutate its stored data.
- Narrow windows, larger text, keyboard navigation, and screen scaling remain usable.

Primary files: new `analyzer_fight_history.py`, `analyzer_catalog.py` if reuse is helpful, `ufc_matchup_analyzer.py`, `analyzer_gui.py`, `analyzer_reporting.py`, `analyzer_results.py`, `analyzer_history.py` if compatibility handling requires it, package allowlists, and report/GUI tests.

## Delivery sequence

| Milestone | Work | Exit condition | Indicative focused effort |
|---|---|---|---|
| M0: Baseline and fixtures | Preserve the current women's fix; capture representative source/result fixtures; document outcome/event/payload contracts | Baseline tests pass and fixtures reproduce the old men's failure | 0.5 day |
| M1: Result handling | Men's draw/NC acceptance, strict audits, training eligibility, export reproducibility | Mixed-outcome staged update and binary-training checks pass for both engines | 1–1.5 days |
| M2: Errors and diagnostics | Typed maintenance errors, retained paths, dialog and retry rules | Failure/recovery matrix passes; all detail links resolve | 1–1.5 days |
| M3: Progress and summaries | Child-event relay, counters, rebuild steps, GUI progress, captured-fight list | Actual progress and summary reconcile with fixtures and installed changes | 1.5–2.5 days |
| M4: Recent fights | Read-only adapters, frozen payload, tab, saved-report compatibility, exports | Identity/date/export/UI acceptance criteria pass | 1.5–2 days |
| M5: Integrated release candidate | Full tests, fresh portable build, real updates/predictions, recovery and layout checks | Reviewable release candidate and verification report | 1–2 days |

Planning range: roughly 6.5–10 focused development days, subject to fixture work, native GUI checks, and source-page behavior. This is a scope estimate, not a runtime or delivery guarantee. A sequential implementation is sufficient; delegation is not required.

Dependency order: establish contracts first, implement outcome handling, add structured errors, then progress/summary integration. Recent-fight implementation follows its own agreed payload contract and is integrated before release verification. Use small reviewable commits per milestone; retain the current uncommitted repair when preparing the implementation branch.

## Verification matrix

| Area | Required evidence |
|---|---|
| Outcomes | W/L in both orders, D/D, NC variants, constrained winner-marker normalization, contradictory markers, missing dates/identities, duplicates, missing/incorrect targets, partial stats |
| Transactions | Valid mixed-outcome update; second-target failure preserves both datasets; rollback; interruption around promotion; restore previous datasets; idempotent repeat |
| Errors | Offline/fetch failure, malformed page, unresolved result, validation failure, low disk space, lock conflict, timeout, missing audit fallback, rollback failure, unknown exception |
| Progress | Partial Unicode lines, final event drain, stale job IDs, malformed/unknown optional fields, phase changes, unknown totals, cancellation, non-cancellable commit, summary counts |
| Recent fights | Men/women fixtures, duplicate names and IDs, aliases, fewer than five bouts, draw/NC, mirrored rows, missing metadata, multiple divisions, same-day ties, strict date exclusion |
| Report states | Prediction, comparison-only, pending/failed/cancelled preview, swapped fighters, changed inputs, old saved payload, updated datasets, restored datasets |
| Export/UI | Shared report values; accented names; HTML escaping; clipboard/TXT/HTML completeness; selectable diagnostics; keyboard focus; narrow windows and actual available DPI settings |
| Models | Forced-fresh men and women predictions, a historical case, existing feature/parity checks, valid probabilities, intended model versions, and confirmed exclusion of new non-binary labels |

Run the full existing suite plus new focused tests once the integrated changes are ready. Do not treat the previous 107-test pass as validation of new code. Use deterministic fixtures for outcome coverage; live UFCStats may not expose a new draw and NC during the release window.

For portable verification, use a fresh disposable extraction with all required datasets and the bundled interpreter. Exercise a real update when new source data is available, plus controlled fixture updates for the required cases. Run integrity checks after update and restore, and verify the repeat update produces no duplicates. Record actual timings without turning them into promised speedups.

## Packaging and release review

1. Update the application version and release-specific documentation together; proposed version is 0.4.0.
2. Add new helper modules to `tools/package_release.py` and audit all new staged/standalone dependencies.
3. Ensure `tools/export_source.py` and applicable adapters reproduce retained engine changes; preserve provenance and refresh exported hashes intentionally.
4. Update README, maintenance/troubleshooting/model notes where behavior changes, screenshots, and release notes with the four concrete improvements.
5. Build the portable ZIP, verify archive members/hashes, extract to a fresh directory, and run native launch/update/prediction/export/recovery checks.
6. Run configured CI for the intended release commit. Distinguish source-only CI from data-equipped native Windows verification.
7. Record completed checks and any unavailable platform checks accurately. Preserve the project's current experimental-release status unless its separate release requirements are satisfied.
8. Deliver the tested candidate, changelog, checksums, and evidence for review. Publishing the release and replacing the user's installed build are later actions; this planning request does not perform them.

## Definition of done

The candidate accepts valid completed draw/NC outcomes in both routes, explains failures with usable retained diagnostics, displays honest progress and reconciled update details, and shows date-correct recent fights consistently across live and saved reports. Its complete update/rebuild/validation/recovery workflow and real predictions pass on a fresh portable extraction. The release package and evidence correspond to the exact tested code and datasets.
