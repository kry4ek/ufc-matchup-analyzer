# Data maintenance and recovery

## Recheck recorded events

**Help → Recheck recent events** fetches an inclusive completed-event range (default 90 days, maximum 20 events) and retains a correction preview. It reports the actual selected events and field-level differences. Oversized ranges, missing known bouts, malformed captures and conflicting identities stop the operation; nothing is deleted because a source response omitted a bout.

**Apply captured corrections** validates the preview digest and baseline dataset hashes under the operation lock, replaces complete paired source records, rebuilds affected advanced/Bayesian features, validates and installs both changed targets atomically. It uses the captured source rather than fetching again. Windows interrupted-transaction recovery and **Restore previous datasets** also apply to corrections. The women's advanced rows are rebuilt from the earliest changed old/new event date onward before Bayesian rebuilding.

Correction summaries distinguish bouts corrected/added, binary rows added, binary rows removed, and signed net change. Last recheck time/range are recorded separately from the last data change. Historical cutoffs exclude later event dates but use the installed source; they do not reconstruct what the source reported on that historical day.

Prepared calculations are stored separately under `.runtime/compute_cache`, bounded to 1 GiB. Changed source contents, dates, settings, implementation or runtime fingerprints prevent incompatible reuse. Clear the calculation cache through Help if needed; this does not delete saved analyses or recovery backups.

Portable users click **Update datasets**. It automatically updates both models using private staging, audits, rebuilding of changed data and validation before installation. No changes means no unnecessary rebuild. Failures preserve installed data. Progress and elapsed time are shown; cancellation stops before commit. Once committing starts, allow it to finish.

The footer refreshes dates and fighter suggestions after success. **Help → Rebuild local features** works offline. **Help → Restore previous datasets** undoes the latest successful update/rebuild after confirmation. Startup checks unfinished journals and recovers inconsistent data before analysis. A still-running maintenance process blocks recovery.

The GUI checks free disk space, retains the latest recoverable backup and at most ten recent audit transactions (plus the retained backup's transaction), and bounds job/session logs. Data lives under `app` in the portable folder. Never delete or move it during an operation.

Completed draws and no-contests in both routes retain two distinct fighter-stat rows with empty win/loss targets. Their statistics remain available for later prefight history, while new binary training rows exclude these bouts. Men's CSVs retain `no_contest`; women's retain `nc`. Inconsistent markers, mismatched identities, missing targets on decisive fights, or numeric targets on draws/NCs block installation. Existing Elo policies and model versions are unchanged.

The progress bar describes the current phase. Event and bout inspection, historical feature construction and mirrored-fight validation show actual counts when known. Rebuild steps are numbered. Other work uses an activity indicator and elapsed time; no overall percentage or ETA is estimated. Installation remains non-cancellable.

Maintenance errors name the affected event/fighters when available, explain the next step and report whether datasets were unchanged, restored, installed or require recovery. **Retry** is available for suitable transient failures after the worker has stopped. **View details** opens retained transaction diagnostics; **Copy diagnostics** copies selected identifiers and a bounded log excerpt with account paths and credential fields redacted. Review copied diagnostics before sharing.

The following CLI workflow is for source users. Use `run.bat` on Windows; macOS/Linux source execution remains unverified.

## Status, backups and saved analyses

**Help → Dataset status and update details** opens a selectable status view. It distinguishes data-through dates, the last successful online update check and the last successful data change. An unchanged update advances the check time without claiming new data. A rebuild does not count as an online check. Restoration records a data change. Successful-operation details persist when the app closes.

The view includes captured decisive bouts, draws, no-contests and binary training rows added. **View updated fights** lists captured bouts and training eligibility for the latest update with changes. The detailed list is retained with its transaction and recoverable backup. If an older audit has been pruned, the view explains its unavailability. Captured fights, fighter-stat rows and mirrored training rows are separate counts. CLI dry-runs report proposed binary rows and never claim installation.

Restore is disabled when there is no recoverable backup. Successful update, rebuild or restoration refreshes dated fighter coverage, suggestions and saved-result compatibility. Old analyses remain viewable; only entries whose actual dataset and calculation fingerprints match can be reused. Maintenance never edits a displayed report. You can copy/save it while maintenance runs.

## Preview, inspect, apply

1. Run `run.bat update --target all`.
2. Open the printed `.runtime/transactions/<ID>/logs` directory. The staged updater logs include row counts, source dates, blocked rows, and the complete safety audit. Audit CSV/JSON files are copied into the transaction's `audits` directory.
3. Confirm the changes are expected. Future events, unresolved results, duplicates, malformed pages, and failed fetches must not be silently accepted.
4. Run `run.bat update --target all --apply`.
5. Run `run.bat doctor`. Predictions launched afterwards use the newly validated data.

Apply performs a new source check. It cannot promise that the source will remain identical to your preview. Every applied change is validated again. All selected targets must finish successfully before installed data is replaced. Draw/no-contest records already present in the historical snapshot can remain as raw source history; binary model training excludes unresolved targets.

Each transaction records commands, logs, safety audits, status and pre-update backups. Maintenance checks space for staging/backups plus a margin. GUI housekeeping retains only the latest recoverable backup; standalone CLI runs retain history until the GUI's next check or explicit maintenance housekeeping. Never delete an active transaction.

## Rebuild local features

`run.bat rebuild --target all` uses local inputs and does not scrape. For men the chain is raw data → prefight training → Elo → v2 features → v3 Bayesian features → validation. Women's rebuilding uses repaired stats and the sig-fixed advanced dataset to rebuild prefight Bayesian smoothing. It does not reconstruct historical source data from scratch.

## Undo or recover

After a reported failure, the analyzer automatically rolls back any file replacements. To recover after a power loss or interrupted commit:

```bat
run.bat doctor
run.bat recover
run.bat doctor
```

`recover` uses the transaction ID from a stale lock and refuses while its owning process is alive. To undo the most recent successful maintenance operation:

```bat
run.bat recover --transaction THE_ID_PRINTED_BY_THE_UPDATE
```

Only the most recent committed transaction may be undone; older backups cannot safely be applied over newer updates. Recovery preserves audit history. If backup files are missing, stop and restore the full project from a known-good copy.

Dataset checksums after a valid update are recorded in `.runtime/local_dataset_state.json`. The original release manifest stays intact. Doctor detects edits outside this workflow. An explicit validated `rebuild` can adopt manually repaired inputs; review them before invoking it.

## Model and application updates

`update` changes fight data and derived features. Download a new portable version into a new folder to update application code/dependencies; it requires no setup. Keep the old folder until the new one passes its startup checks and a prediction. Source users rerun source setup as documented. Do not transplant a `.venv` between computers.

Algorithm changes require separate evaluation, leakage-safe validation, and an explicit model-version decision. They are not promoted by a successful data update.
