# Release verification: v0.3.0 portable Windows local candidate

**Implemented and locally verified; the bundled portable release remains blocked.** Dataset redistribution permission, clean Windows 10/11 machines and actual 100/150/200% display-scale checks are unavailable. The owner has requested a source-only development preview: uploading code/documentation/tests does not include the datasets/runtime or clear these gates. The tests below were performed locally before that upload. [release_checks.json](release_checks.json) records every gate; [verification_evidence.json](verification_evidence.json) contains sanitized measurements and evidence scope.

## Delivered behavior

The compact native Tk/ttk app prepares a dated comparison before fitting the unchanged men's v3 and women's ensemble algorithms. It adds statistics-only comparisons, Overview/Fighter comparison/Full report tabs, grouped tables and explanations, a probability bar, calendar, dated coverage/division warnings, automatic suggestions, Swap, remembered selections and display settings, exact saved-result reuse, up to 50 local analyses/50 MB, TXT and standalone offline HTML exports. Failed/cancelled predictions retain their prepared comparison without being recorded as successful predictions.

All table/text/HTML views share raw/formatted metrics and support notes. No prediction is fabricated in statistics-only mode. Men’s confidence classification and women’s reliability remain distinct. A−B differences are descriptive, not a model explanation. Historical statistics exclude same-date and future fights; profile-correction caveats remain. Explicit earlier CLI training cutoffs remain distinct from the fight date used for statistics.

Workers retain subprocess isolation, operation locks, process-tree cancellation and safe maintenance transactions. Every progress/preview/result message includes request/job identity. Read/copy/save continues while work runs. A result completed while another analysis is open is available through Open new result.

## Baseline and package

Restored 87 curated v0.2.1 files and all 15 datasets by manifests/hash checks into the selected project. The existing `.git` and original research workspace were preserved. Research source commit: `6900c7ff3c8af887e9155c77aaf42475decaaeac`. A fresh allowlist export reproduced all 30 engine/helper files and all dataset hashes after applying the reproducible workflow adapters.

The private runtime is CPython **3.14.7 x64**, matching **Tcl/Tk 9.0.4**, and **18 locked dependencies**. Calendar, tables, HTML and history add no runtime libraries. The Windows-subsystem native launcher and workers open without an owned console in tested runs. Static closure checked **299 AMD64 PE files**, including delayed imports. Verified runtime/wheel/Tk inputs are recorded in runtime_inputs.json and BUILD_INFO.json.

Required data totals **206,791,890 bytes (197.21 MiB)** through **2026-09-26**. The Windows ZIP is approximately **120.5 MiB** and its complete extracted inventory approximately **406 MiB**; the matching dataset ZIP is approximately **43.1 MiB**. The source archive excludes data/runtime/state. Exact final archive bytes and SHA-256 hashes are recorded beside the ZIPs in archive_manifest.json and SHA256SUMS.txt. PACKAGE_MANIFEST.json inventories packaged files. User results/preferences/logs/backups are excluded from archives.

## Fresh verification on this machine

Environment: Windows 10 Pro x64 build 19045, Intel i7-4510U/four logical processors, approximately 16 GiB RAM; actual display scale 125%. Source and portable checks use bundled Python 3.14.7. Local logs and disposable extractions stay outside the public source.

| Check | Outcome and scope |
|---|---|
| Regression | **96 tests, no skips**, 12.567 seconds. Identity/date/history/protocol/report/export/transaction/failure states; real native Tk tests. |
| Real model regression | Both routes, forward/reverse/historical/single-worker; eight frozen-ZIP and **eight delivery-ZIP** real cases matched v0.2.1 probabilities within **1e-12** and overlapping raw metrics. Men: forward 0.8229788712684363; women: 0.485904994646593. No cache or mock counted as a model pass. |
| Feature parity/leakage | **10,800** comparisons, 20 fights, 270 features, both orientations; zero mismatches/missing features, maximum difference 2.84e-14. Target/same-event/date checks and rebuilt data validators passed. |
| Statistics/progress | Actual comparisons do not fit prediction models; metrics appear before training. Cancellation after preparation retains metrics; zero-history confirmation can decline without launching work. |
| History | Exact reuse with full integrity checks; no duplicate entries; disabled history stops storage/reuse. Corrupt/unsupported entries, interrupted writes, limits, write failure and invalidation are tested. Actual Recent analyses Open/Delete/Clear and viewing older results during cancellation passed. |
| GUI | Suggestions/duplicate details/date/calendar/leap years/category/Swap/stale banner/filter/details/collapse/font sizes; simulated 100/125/150/200% Tk layouts on all three tabs. Actual DPI availability remains limited. |
| Exports | Full UTF-8 clipboard/TXT/HTML share metrics even with filtering. Real native TXT Save, Cancel, declined overwrite; real HTML Save action with correct `.html` default. Standalone HTML rendered offline and printed to PDF; dynamic HTML escaped. |
| Maintenance | Bounded live one-event all-target update: already current, **53.88 seconds**. Full local both-target rebuild **535.91 seconds**, validated/committed; GUI restore returned **all 15 exact original hashes**. Real network and malformed-page failures preserved data. No genuinely new live fight promoted. |
| Maintenance faults | Fixtures cover valid additions, duplicate/future/unresolved results, incomplete audits, malformed pages, low disk space, rebuild/second-target failure, interrupted commits and recovery. Cancelled/failed work is not mistaken for a completed result. |
| Developer setup | Eight PowerShell tests; existing supported installation tested. Missing installation, declined install and unavailable installer branches mocked; not clean-machine proof. |
| Dependency constraints | All 18 runtime distributions and 15 applicable declared dependency constraints passed. The parser was QA-only, not an added runtime dependency. |

The delivery ZIP was freshly extracted into separate paths containing spaces and Unicode. Its eight forced-fresh real predictions passed normal parallel, explicit single-worker, reversed and historical cases, with correct algorithms, dated raw metrics, probability bounds, weighted ensemble agreement, actual clipboard/TXT exports and zero visible owned console windows. Under competing release load, men's operations measured 136–251 seconds, women's 146–192 seconds. Delivery statistics-only/reuse/export/cancellation checks and real history/Save dialogs also passed. Native EXE startup passed offline with conflicting Python/Tcl/Tk variables, a PATH without Python, and another working directory.

Final packaging changes only documentation/evidence/screenshots and the developer QA allowance, followed by exact archive checks and a final fresh extraction/native launch. Application, runtime, native launcher and dataset identity are compared against the tested delivery package; all final archive hashes/CRCs/member hashes are checked separately. Final file hashes are outside the archives in archive_manifest.json/SHA256SUMS.txt, avoiding self-referential checksums.

Full maintenance was rerun on disposable extracted data. GUI callback fixes subsequently added targeted tests for maintenance failures preserving a displayed prediction, and exposing a cancelled comparison while another analysis is open. A native HTML-format check exposed Windows retaining a `.txt` filename when changing the dialog filter; the app now offers explicit TXT/HTML actions before opening the native dialog. These fixes passed the full regression suite and native checks.

## Measurements and limits

Sequential one-worker CLI comparisons, using identical verified datasets/Python binaries after other heavy release checks, measured men **103.943 s → 85.007 s** and women **146.376 s → 119.809 s**. Probabilities were unchanged. These are one paired measurement per route, not a promised speedup or an isolation-controlled benchmark. Fresh GUI runs under concurrent load took longer; per-case stage, rendering and memory samples are in the evidence file.

Statistics-only took **83.171 s men** and **13.520 s women**, with first comparison at 74.619/11.533 seconds. Exact verified reuse took **7.796/1.182 seconds**. Men's advanced preparation dominates its prediction; women avoid cross-validation in comparison mode. Rendering measured about 20–39 ms in the eight frozen-ZIP cases.

The initial five-second engine sampler suggested a men's increase (347.1 to 416.7 MiB). A fresh 100 ms investigation using OS PeakWorkingSetSize measured 391.86 MiB for v0.2.1 and 424.86 MiB for v0.3 (+8.42%). These are real one-worker predictions with identical data/runtime; tree totals remain samples. See the evidence file for both measurements.

Sampled whole-app working sets in frozen-ZIP cases were roughly **524–531 MiB men**, **996–998 MiB women parallel**, and **300–302 MiB women single-worker**. Working sets can double-count shared pages; samples can miss brief peaks. These are observations, not minimum hardware requirements. Peak additional maintenance runtime storage was **221,250,130 bytes (211.00 MiB)**, sampled every 250 ms during rebuild/update/restore. Keep at least **1 GB free** for this snapshot; future changed-data updates can need more. No fitted models are cached.

A single-pass hash/schema prototype was profiled in alternating order. Warm scans were both about **12.25 seconds**; it offered no established warm-run benefit, so full production integrity/semantic validation remains unchanged. Automatic reuse also hashes actual content; modification time alone is never trusted.

Three first-use Unicode-folder launches exceeded the former **90-second QA timeout**; their logs are retained. A new unmodified extraction's checks then completed in **104.607 seconds** under concurrent model load: 32.183 seconds validating data, 8.011 importing NumPy, 14.842 pandas, 42.377 scikit-learn. The test allowance is now 300 seconds; this changes no end-user runtime behavior. Another fresh real GUI first launch passed without restarting in **34.88 seconds**. The underlying OS/disk import slowdown is not attributed to a specific cause, and these are not clean-OS successes.

## Reproduce checks

Developer commands from source (install the matching dataset archive first):

```bat
python -m unittest discover -s tests -v
powershell -NoProfile -ExecutionPolicy Bypass -File tests\test_setup.ps1
python tools\audit_release.py
python tools\benchmark_validation.py --out verification\validation-profile.json
python tools\verify_archives.py --directory release-assets
python tools\package_release.py --check-publication
```

From a freshly extracted portable folder, use its interpreter for tools in the source checkout:

```bat
"runtime\python.exe" "SOURCE\tools\check_portable.py" --target men --full --offline --out verification\men\report.json
"runtime\python.exe" "SOURCE\tools\check_portable.py" --target women --full --offline --out verification\women\report.json
"runtime\python.exe" "SOURCE\tools\check_usability_portable.py" --out verification\usability\report.json
"runtime\python.exe" "SOURCE\tools\check_maintenance_gui.py" --out verification\maintenance\report.json
"UFC Matchup Analyzer.exe" --smoke-report verification\launcher.json
```

`SOURCE` denotes the source checkout path, not a shipped portable test directory. [Build instructions](docs/BUILDING.md) include native Save, layout, and history tools. Portable GUI tests assert interpreter search paths stay inside the bundle. Publication gate failure is **expected** until blockers below clear.

## Remaining release blockers

- Dataset redistribution basis is unresolved; neither bundled datasets nor matching dataset archives may be published.
- Clean Windows 10 and Windows 11 x64 without Python/Git/development tools have not been available.
- Actual Windows 100%, 150% and 200% display-scale checks remain unavailable; Tk simulations do not replace them.
- Public repository/pinned dataset URL and actual published-download checks are pending authorized publication. The unsigned launcher's SmartScreen reputation is unverified.
- The included Windows/macOS/Linux source CI workflow has not been run remotely; macOS/Linux source execution is separately unverified.

No required unavailable check is counted as passed. The delivered ZIP is a **local review candidate**, preserving download → extract → open folder → double-click EXE.

## Help menu fix — October 1, 2026

The Help popup was repeatedly redrawn because the 150 ms controller poll configured identical enabled/disabled entry states. Entry configuration now occurs only when availability changes. Installation/rebuild remain disabled while work runs, and Restore still requires an available backup and an idle app.

Both new regression tests failed on the original code (20 idle polls triggered 60 menu configurations). The corrected source passes **98 tests, no skips, in 15.905 seconds**. The actual packaged GUI with its bundled runtime and real startup/installation-check workers also passed native posted-menu checks: both ready and busy states stayed open for approximately 2.5 seconds, with 20 scheduled ticks and **zero redundant menu configurations**. Normal menu availability returned after the worker completed.

Computer Use could launch the executable but could not capture its window: `FrameArrived timed out`; capture retry reported `window capture timed out`. This is an unavailable visual check, not a visual pass. Native Tk popup and state-transition checks provide fresh automated evidence. This fix changes GUI state updates only; previous model, feature/leakage, runtime and dataset verification remains retained evidence. Existing publication/clean-machine/display-scale blockers remain unchanged. Local detailed logs: work/help-menu-before.log, work/help-menu-regression.log and work/help-menu-native.json.

## Existing comparison navigation — October 1, 2026

Compare statistics only remains useful before a prediction: it prepares metrics without fitting prediction models. After a completed prediction or comparison for the same canonical matchup, it now opens the existing Fighter comparison tab instead of starting another calculation. It retains the prediction, report type, generation time, complete TXT/HTML exports and history entry. This is navigation within an already displayed report; fresh calculations and saved-result loading retain full data verification. Recalculate still forces new computation.

The source passes **104 tests, no skips, in 12.868 seconds**; the final GUI subset passes **18 tests in 7.331 seconds** after fixture adjustments. Cases cover unchanged results, history disabled, repeat clicks, changed fighters/order/IDs/division/category/dates/cutoff, outdated contexts, missing metrics, incomplete states, manual profiles and forced recalculation.

Fresh offline GUI/worker predictions on disposable portable copies passed for both engines and matched baseline probabilities within 1e-12, with identical overlapping raw metrics. Men: 0.8229788712684363, prediction 160.79 seconds under concurrent test load, existing comparison **0.0662 seconds**. Women: 0.485904994646593, prediction 130.52 seconds, existing comparison **0.1006 seconds**. Each button check confirms no new worker, unchanged report/metric/timestamp values and no extra history entry; actual clipboard and TXT export checks passed. These navigation measurements include selecting the tab and processing UI events; they are observed timings, not a guaranteed latency. Models, runtime and datasets are unchanged. Existing publication, clean-machine and actual display-scale blockers remain unchanged.

Evidence: work/comparison-navigation-tests.log, work/comparison-navigation-final-ui.log, work/comparison-navigation-men/report.json and work/comparison-navigation-women/report.json. Portable verification helpers now check navigation instead of expecting a second cached computation for an already displayed result.
