# v0.4.0 experimental prerelease

- Both dataset updaters accept consistent completed draws and no-contests. They retain two source-stat rows and exclude these bouts from new binary training labels. Contradictory results and incomplete identities remain blocked.
- Maintenance errors now include a readable reason, affected bout context, truthful recovery state, retained diagnostics, sanitized diagnostic copying and a manual Retry action for suitable transient failures.
- Dataset maintenance relays structured child progress, displays actual current-phase counters and numbered rebuild steps, and retains captured-fight/outcome/training summaries with transaction audits.
- Recent fights shows each fighter's five most recent eligible UFC bouts across divisions, strictly before the selected date. Previews, statistics-only results, completed/saved analyses, clipboard, TXT and offline HTML use the same frozen list. Old saved analyses remain readable.

The men's `v3_bayes_smoothed` algorithm, women's `v1_current_ensemble`, feature definitions, calibration and existing Elo policies are retained. A valid update can change subsequent predictions by adding new source data. This release does not add automatic historical rechecking or model-training optimization.

See the release verification report for actual checks and remaining platform limitations. Download and extract the complete v0.4.0 Windows ZIP into a new writable folder to use the updated app. Keep your previous installation until the new folder passes its startup checks and a prediction.
