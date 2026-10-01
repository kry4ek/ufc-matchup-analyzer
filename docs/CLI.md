# CLI and manual source setup

The portable Windows candidate needs no setup. These commands are for source users. Git history and automatic source downloads exclude datasets. Download the matching **ufc-matchup-analyzer-datasets-v0.3.0.zip** from [Releases](https://github.com/kry4ek/ufc-matchup-analyzer/releases/tag/v0.3.0); cloning the repository alone is insufficient. `dataset_manifest.json` lists every prerequisite. Dataset redistribution rights remain unresolved, as explained in [DATA_NOTICE.md](../DATA_NOTICE.md).

## Windows

Install 64-bit Python 3.14.7 and obtain the matching data archive, then run:

```bat
setup.bat --dataset-archive "C:\Downloads\ufc-matchup-analyzer-datasets-v0.3.0.zip"
run.bat doctor
run.bat predict men --fighter-a "Islam Makhachev" --fighter-b "Justin Gaethje" --division "Lightweight" --fight-date 2026-10-10 --out predictions\men.json
run.bat predict women --fighter-a "Valentina Shevchenko" --fighter-b "Manon Fiorot" --division "Flyweight" --fight-date 2026-10-10 --workers 1 --out predictions\women.json
run.bat compare men --fighter-a "Islam Makhachev" --fighter-b "Justin Gaethje" --division "Lightweight" --fight-date 2026-10-10 --out predictions\comparison.json
```

Setup creates `.venv` and is rerunnable without overwriting data. `run.bat` uses that environment without activation; no arguments opens the console menu. Launch the source GUI with `.venv\Scripts\python.exe analyzer_gui.py`; its checks require Python 3.14.7.

`--fighter-a-id` / `--fighter-b-id` resolve supported duplicate men's names. `--profiles` supplies explicit advanced CLI profiles. Women's duplicate names cannot safely be resolved by ID with the current engine. Unknown identities are never guessed.

`compare men|women` prepares the same dated comparison and Bayesian inputs without fitting prediction models. Its JSON has `result_state: comparison` and no probability/winner/reliability fields. Existing prediction JSON fields are retained. Predictions emit an early comparison event internally for the GUI, then finish with the unchanged model policies.

CLI commands compute afresh by default. `--use-cache` explicitly allows exact content-matched saved-result reuse; `--force-recalculate` explicitly bypasses it. These options are mutually exclusive. Completed commands participate in local history unless the GUI history setting is disabled. Fitted model binaries are not cached. Historical cutoffs, manual-profile hashes, fighter order and worker mode are part of compatibility. A manual-profile CLI analysis can be viewed/exported in the GUI, but must be recalculated with its original profile file through the CLI.

```bat
run.bat update --target all
run.bat update --target all --apply
run.bat rebuild --target all
run.bat recover --transaction TRANSACTION_ID
```

CLI update defaults to a dry-run; the GUI explicitly requests automatic apply. Targets are `men`, `women` or `all`. On disposable data, `--max-events 1 --from-date 2026-09-26` bounds a live check. Dry-runs preserve installed data and retain audits. Applying checks the source again and validates all targets before promotion.

GUI and CLI share an operation lock. Logs live under `.runtime`. Prediction supports `--verbose` and `--workers 1`. Men's `--as-of-date` must precede the fight date and cannot exceed today; women always use strictly pre-fight history.

## macOS/Linux — execution unverified

Install Python 3.14 and Tcl/Tk for the GUI. Obtain the matching data archive; its redistribution restriction still applies.

```sh
python3.14 -m venv .venv
.venv/bin/python -m pip install --only-binary=:all: -r requirements.lock
.venv/bin/python setup.py --dataset-archive /path/to/ufc-matchup-analyzer-datasets-v0.3.0.zip
.venv/bin/python ufc_matchup_analyzer.py doctor
.venv/bin/python ufc_matchup_analyzer.py predict men --fighter-a "Islam Makhachev" --fighter-b "Justin Gaethje" --division Lightweight --fight-date 2026-10-10 --workers 1
.venv/bin/python ufc_matchup_analyzer.py predict women --fighter-a "Valentina Shevchenko" --fighter-b "Manon Fiorot" --division Flyweight --fight-date 2026-10-10 --workers 1
```

The lock was validated on Windows. Manual commands and source-only CI do not establish data-equipped macOS/Linux readiness. No portable package for those platforms is included.
