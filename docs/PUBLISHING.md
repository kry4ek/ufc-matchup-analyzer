# Publishing source and portable releases

The public repository is `kry4ek/ufc-matchup-analyzer`. Keep datasets, bundled runtime, environments, local state and generated results outside source Git history. The explicit source allowlist includes code, documentation, tests, licenses, manifests and screenshots. Portable, source and dataset ZIPs are separate GitHub Release assets.

## Current experimental publication

On October 1, 2026, the owner requested publication of the full portable app and accepted the possibility of GitHub taking it down. The candidate is a **prerelease**, with unresolved dataset redistribution rights and unavailable clean-machine/display-scale checks disclosed in the README and release notes. This decision is separate from the verification gate. Keep dataset `redistribution_status` as `review_required` and keep failed/unavailable checks visible. Do not claim that permission was obtained or that the standard gate passed. See [DATA_NOTICE.md](../DATA_NOTICE.md) and [release verification](../RELEASE_VERIFICATION.md).

The release includes:

- `ufc-matchup-analyzer-v0.3.0-windows.zip`: the complete Windows x64 app.
- `ufc-matchup-analyzer-source-v0.3.0.zip`: curated source, without data/runtime.
- `ufc-matchup-analyzer-datasets-v0.3.0.zip`: matching source-user snapshot.
- `SHA256SUMS.txt`, `archive_manifest.json` and the verification report.

Use a draft release while uploading and checking all assets. Publish it only after the source/ZIP inventories, hashes, dependency/secret scans and local package checks finish successfully. Record actual published-download checks after publication; never substitute earlier local evidence for a download test.

## Standard fully verified release

For a stable release, resolve dataset redistribution requirements and record the supporting evidence in DATA_NOTICE.md. Only then change `redistribution_status` to `cleared`. Complete every required pre-publication check. A check is PASS only with evidence; unavailable Windows checks still block this gate. The download check has phase `after_publish`. macOS/Linux execution is separately labelled according to its actual verification status.

From a data-equipped source checkout:

```bat
.venv\Scripts\python.exe tools\package_release.py --repository kry4ek/ufc-matchup-analyzer --portable-folder "dist\UFC Matchup Analyzer" --out-dir release-assets
.venv\Scripts\python.exe tools\verify_archives.py --directory release-assets
.venv\Scripts\python.exe tools\audit_release.py
.venv\Scripts\python.exe tools\package_release.py --check-publication
```

`--check-publication` continues to fail for the current experimental candidate; owner acceptance does not turn it into a verified stable release.

Review Git status, the allowlist, export hashes and archive checksums. Push only curated source and attach the archives to a versioned release. Source setup uses the manifest's repository and exact dataset version, never a changing latest-data URL. Download the published portable ZIP, verify its checksum, extract and launch it using its own runtime. Run both documented examples offline, and verify the matching dataset download from a source-only setup.

The curated repository has fresh history, separate from the research checkout. Future snapshots need their own versions, hashes and verification evidence.
