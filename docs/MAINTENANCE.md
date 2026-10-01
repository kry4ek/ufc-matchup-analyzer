# Data maintenance and recovery

Portable users click **Update datasets**. It automatically updates both models using private staging, audits, rebuilding of changed data and validation before installation. No changes means no unnecessary rebuild. Failures preserve installed data. Progress and elapsed time are shown; cancellation stops before commit. Once committing starts, allow it to finish.

The footer refreshes dates and fighter suggestions after success. **Help → Rebuild local features** works offline. **Help → Restore previous datasets** undoes the latest successful update/rebuild after confirmation. Startup checks unfinished journals and recovers inconsistent data before analysis. A still-running maintenance process blocks recovery.

The GUI checks free disk space, retains the latest recoverable backup and at most ten recent audit transactions (plus the retained backup's transaction), and bounds job/session logs. Data lives under `app` in the portable folder. Never delete or move it during an operation.

The following CLI workflow is for source users. Use `run.bat` on Windows; macOS/Linux source execution remains unverified.

## Status, backups and saved analyses

**Help → Dataset status and update details** opens a selectable status view. It distinguishes data-through dates, the last successful online update check and the last successful data change. An unchanged update advances the check time without claiming new data. A rebuild does not count as an online check. Restoration records a data change. Successful-operation details persist when the app closes.

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
