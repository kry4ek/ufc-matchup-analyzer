# Prepare and publish a release

The bundled deliverables are local review candidates. The owner has requested a source-only repository named `ufc-matchup-analyzer`; its README identifies it as a development preview. This source upload includes the explicit public file allowlist and excludes datasets, runtime/environment folders, generated reports, local preferences, secrets and all bundled release archives. Source publication does not clear the portable-release gates or make predictions runnable from a fresh clone.

For the source preview, audit the allowlist, commit only reviewed source/documentation/tests, and push fresh history. Keep `dataset_manifest.json`'s `redistribution_status` and dataset `release_repository` unchanged: there is no downloadable data release to configure. Do not create a portable release tag or upload the dataset/Windows ZIPs. GitHub Actions source checks may run without the data; their skips do not constitute full prediction/portable validation.

The following steps apply to a future **bundled portable release**, not the source preview. Use the release report and machine-readable `release_checks.json` to determine its readiness:

1. Resolve dataset redistribution requirements and record supporting evidence in `DATA_NOTICE.md`. Only then set `dataset_manifest.json`'s `redistribution_status` to `cleared`.
2. Complete every required pre-publication release check. A check is `PASS` only with evidence; failed or unverified checks block publication. The public-download smoke check is explicitly marked `after_publish` and is performed after release assets become available. macOS/Linux source checks are labelled optional for this Windows-only portable release; do not claim those platforms are verified. Keep the report accurate rather than replacing statuses to bypass the gate.
3. Choose the publishing GitHub account and configure the version-pinned data URL:

   ```bat
   .venv\Scripts\python.exe tools\package_release.py --repository YOUR_ACCOUNT/ufc-matchup-analyzer
   .venv\Scripts\python.exe tools\package_release.py --check-publication
   .venv\Scripts\python.exe tools\package_release.py --portable-folder "dist\UFC Matchup Analyzer"
   ```

4. Review the Git status, exported-file manifest, secret/path scan, and archive checksums. Source Git history must exclude datasets, `.venv`, `.runtime`, caches, local settings, and generated predictions.
5. Configure your Git author name/email, commit the staged clean source, create `ufc-matchup-analyzer`, push its clean history, and tag `v0.3.0` only after the gate passes. Upload the portable Windows ZIP, source ZIP, dataset ZIP and checksums as release assets. Runtime binaries and datasets remain outside Git history.
6. Download the actual public portable ZIP to a clean Windows machine. Verify its checksum, Extract All, double-click the EXE, and run both documented examples without installing anything. Check a source-only download's version-matched data fetch too. Record public-download verification.

Do not use Git LFS for the initial data distribution: large changing CSVs stay outside Git history. Public source setup derives its dataset download URL from the manifest's repository and version, never from an unversioned latest-data URL.

The initial repository is a fresh curated history, independent of the private/local research checkout. Future data snapshots should use new dataset/release versions, updated hashes, and their own verification evidence.
