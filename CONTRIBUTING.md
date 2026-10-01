# Contributing

Use 64-bit Python 3.14.7 for the GUI/portable build. Run setup, then use the project-local interpreter. Runtime dependencies are locked; tests use standard-library unittest. The portable end-user package requires no setup. See `docs/BUILDING.md` for verified build inputs and repeatable launcher/package builds.

The source Git tree does not include prediction data. To check it without the matching snapshot, first install 64-bit Python 3.14.7, then use PowerShell:

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install --only-binary=:all: -r requirements.lock
.venv\Scripts\python.exe -m pip check
$env:ANALYZER_SOURCE_ONLY = '1'
.venv\Scripts\python.exe -m unittest discover -s tests -v
.venv\Scripts\python.exe tools\audit_release.py --source-only
```

This mode uses fixtures and explicitly skips data-dependent checks. The local dataset-free Windows run discovered 104 tests: 101 passed and 3 were skipped. It is not a complete model/portable-release validation. Remove the source-only flag (`Remove-Item Env:ANALYZER_SOURCE_ONLY`) before running the full data-equipped suite below. Setup and prediction require all matching data prerequisites listed in `dataset_manifest.json`; copy those CSV files from the version-matched portable package into a fresh checkout. There is no separate public dataset ZIP, and the rights review remains unresolved.

```bat
.venv\Scripts\python.exe -m unittest discover -s tests -v
powershell -NoProfile -ExecutionPolicy Bypass -File tests\test_setup.ps1
.venv\Scripts\python.exe tools\audit_release.py
```

The retained engines are under `mens_ufc_model` and `womens_ufc_model`. Their helpers are intentionally retained where live prediction or feature rebuilding imports them, even if filenames contain older model-version names. The public interface is `ufc_matchup_analyzer.py`; installation, data checks, and transactional maintenance are separate modules.

The research workspace remains the source of model algorithms. `source_manifest.json` records the source commit, explicit export allowlist, original source hashes, and hashes after public-interface adaptations. `tools/export_source.py` refreshes those selected engine/data files from an explicitly supplied research path; do this in a new candidate directory, review public adaptations, run all checks, and compare predictions before release. Never copy local environments, caches, agent settings, or research outputs into a public repository.

Avoid changing model features, hyperparameters, calibration, or confidence policy during packaging work. Model changes need separate leakage-safe evaluation. Changes to maintenance must test rollback, interruption recovery, all selected targets, and audit completeness. Do not assert release readiness from exit codes alone: inspect probabilities, dates, schemas, and the structured release gate.

When updating dependencies, validate the entire lock on clean Windows, Linux, and macOS environments, including real prediction smoke checks. The CI workflow runs source-only safety checks without requiring datasets; data-dependent release checks are separate. The standard stable-release gate remains unsatisfied for the owner-requested experimental publication described in docs/PUBLISHING.md.
