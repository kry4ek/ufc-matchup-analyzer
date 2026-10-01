# Troubleshooting

**App does not start:** choose Extract All on the ZIP. Keep the executable, `app` and `runtime` together in a writable local folder. The portable launcher is the EXE. Startup details are in `app/.runtime/logs/gui-startup.log` if Python could start.

**Windows or security software blocks it:** review the actual message and file origin/checksum. The review launcher is unsigned; SmartScreen reputation is not verified. Do not disable security software for an unexpected or altered file. An administrator may restrict portable programs.

**Missing Python/libraries:** the portable ZIP includes them. Extract a fresh complete copy to repair missing runtime files. Source code ZIP users need [developer setup](CLI.md).

**Permissions/read-only folder:** move the complete folder into Documents. Avoid Program Files and running inside the ZIP. Datasets, staging, preferences, logs and temporary files need write access. Administrator access is normally unnecessary.

**Missing/corrupt data:** use Help → Check installation. Extract a fresh complete ZIP into a new folder for missing raw files or unexpected checksum changes. Keep the old folder for logs/results. Rebuild repairs derived features when local inputs are intact; it cannot recreate missing historical source data.

**Fighter not found:** check spelling, the dropdown, or offered close matches. Update data for newly recorded fighters. Suggestions require selection. Insufficient history may still prevent analysis. The first GUI does not expose manual debutant profiles.

**Duplicate name:** choose the identity matching birth-date/weight details. Women's duplicate identities are blocked where the engine cannot distinguish them safely.

**Invalid date:** use YYYY-MM-DD. Historical/future dates are supported with sufficient eligible history. Very early dates can leave too few training rows.

**Slow analysis:** models train on your CPU. Allow a few minutes; elapsed time continues while the window responds. Cancel stops analysis. Packaging does not change training speed.

**Slow statistics comparison:** if you already have a completed report for the unchanged matchup, Compare statistics only opens its Fighter comparison tab without reloading datasets. It preserves the existing prediction, timestamp and exports. A new or outdated matchup still needs dated advanced features; men's preparation can take nearly as long as a prediction, while women's comparison skips lengthy model cross-validation. Loading a saved result for a new calculation still verifies dataset contents. Use Recalculate when you explicitly want fresh computation.

**Recent analysis says Outdated:** its datasets, implementation or settings differ from this installation. It remains readable. Recalculate creates a current result; reopening an old result does not update it. History errors never discard a completed report: copy or save it to a writable folder.

**First launch takes a long time:** startup verifies the datasets and imports the bundled libraries, then prepares the fighter list. Watch the status message and allow a minute or two, especially while other programs use the CPU/disk. A cold-start diagnostic completed in 105 seconds under competing load; other fresh launches were quicker. The earlier 90-second test limit was too short and has been increased. Persistent startup failure requires inspecting diagnostics, not assuming the app is ready.

**Parallel-worker permission error:** the app offers a one-worker retry for this recognized failure. Other errors retain a diagnostic log and are not silently retried.

**Network error:** check internet, VPN/proxy restrictions and source availability, then retry. Existing data is preserved. Dataset updates do not download a new app or runtime.

**Disk space:** free space on the app's drive. Staging/backups need extra copies; the app reports its calculated minimum. Keep at least 1 GB free for this snapshot.

**Interrupted update:** reopen the app. It checks journals and restores a consistent state before enabling analysis. Wait if another operation is running. Failed recovery remains visible and blocks analysis; preserve its logs.

**Restore previous datasets:** Help → Restore previous datasets undoes the latest successful update/rebuild after confirmation. Older backups are removed during GUI housekeeping; audit logs are bounded.

**Save/copy:** choose a writable save folder. Cancelling Save writes nothing. Copy refers to the displayed analysis even after editing inputs. Ctrl+A selects results; Ctrl+C copies a selection. Invalid filename characters are sanitized. Exports use UTF-8.

Choose **Save TXT / HTML → Save HTML report** for a browser-friendly comparison. Ctrl+S opens text saving. All sections are exported even when a table filter is active. Declining overwrite preserves the existing file.

Portable diagnostics are under `app/.runtime`; source diagnostics are under `.runtime`. Logs can include fighter names and local paths, so review them before sharing.
