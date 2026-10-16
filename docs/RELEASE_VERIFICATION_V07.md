# v0.7 local experimental candidate

Verified locally on 15 October 2026. v0.7 has not been published. Current
machine-readable results are in `verification_evidence.json`; detailed coverage
is in [v0.7 verification](docs/V0_7_VERIFICATION.md). Historical
[v0.6 verification](docs/RELEASE_VERIFICATION_V06.md) is preserved separately.

| Check | Result |
| --- | --- |
| Native regression | 204 tests, zero failures/errors/skips; 19.777 seconds |
| Setup | Eight checks passed; installer branches mocked |
| Model decision | Corrected women's policy promoted after complete development/final evaluation and parent/export parity |
| Model accounting | Women 165 development + 72 final; men 824 + 454; zero failed/remaining cases |
| Nested audit | 110 women's dates, 1,650 disjoint boundaries; preprocessing fits only inside its fitting block |
| October data | All 15 parent/app hashes agree; 207,401,438 bytes; latest 2026-10-10 |
| Live update | 22 men bouts, four women bouts; one draw retained in history and excluded from binary training; repeated update makes no changes |
| Corrections | Real NC/draw rebuild, promotion and restore pass for both families; all hashes restored |
| Portable | Both families pass offline forward/reverse, single-worker and historical cases; no visible child consoles |
| Old policy | Actual v0.6 women prediction imported, viewed and copied unchanged; new-policy reuse blocked; undo preserves originals |
| Native saves | Actual TXT/HTML filenames/content pass, including TXT cancellation and declined overwrite |
| Native dependencies | 299 AMD64 PE files, no missing normal/delay imports detected |
| Layout | Populated 100/125/150/200% Tk simulations and focus traversal pass; these are not actual OS scale tests |
| Delivery archives | Final source-only tests, member hashes/CRCs, fresh extraction and native EXE startup are recorded beside the local archives in `candidate_verification.json` |

Women's final log loss is 0.6131 versus 0.6273 for the frozen reference; Brier is
0.2120 versus 0.2179. The paired event-date log-loss interval [-0.0359, 0.0079]
includes zero. These remain limited retrospective findings, with later source
corrections, repeated fighters and incomplete prior-exposure knowledge. See
[model decision](docs/V0_7_MODEL_DECISION.md) and [model report](docs/MODEL_VALIDATION.md).

The evaluated September snapshot is frozen separately from the October
installation. A current-data mismatch is expected; updated hashes are not
substituted into the historical evaluation. Women's inherited numerical
reliability grade is withheld because its thresholds were not validated for
the corrected policy.

The controlled representative men's request median fell 90.720 → 50.851 seconds
(43.95%) with numerical parity. This benchmark used identical model semantics
and September data. Refreshed portable forward requests took 76.650 seconds
(men, automatic workers) and 30.310 seconds (women). These functional timings
are not a controlled cross-policy speed comparison. See the
[benchmark conditions](docs/V0_7_BENCHMARK.md).

The portable uses unchanged, manifest-verified Python 3.14.7, locked libraries
and launcher inputs. It includes all 15 matching datasets. Source archives omit
datasets/runtime/state, and no standalone dataset archive is produced. Runtime
state, histories, calculation caches and backups are excluded from delivery.

Clean Windows 10/11 and actual 100/150/200% OS scaling checks remain outstanding
at the user's request because no test environments are available. Developer-
machine success and simulations do not substitute for them. Dataset rights
remain `review_required`, and the launcher is unsigned. Remote CI and public
asset-download verification belong to a separately requested publication.
The stable/publication gate is not passed by this local experimental candidate.
