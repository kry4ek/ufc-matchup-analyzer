# v0.5 implementation plan

Prepared: 12 October 2026. Status: all four features implemented and local workflow verification passed; portable candidate prepared. See [verification](V0_5_VERIFICATION.md) and [record contracts](V0_5_DATA_CONTRACTS.md).

## Outcome and scope

Deliver four improvements to the existing Windows portable, single-matchup app, in this order:

1. Faster calculations when moving between matchups.
2. A bounded recheck that detects corrections to already recorded fights.
3. A concise, evidence-backed matchup summary.
4. A comparison between two saved versions of a matchup.

Keep the current men's and women's algorithms, calibration, features, random seeds, and engine-specific Elo policies. Data corrections can legitimately change later predictions. Preserve the current recent-fights panel, exact-result reuse, statistics-only workflow, cancellation, immutable saved reports, exports, and transactional maintenance.

The active project is `E:\soft\UFC Matchup Analyzer Project`; the old C path is a junction. Keep benchmarks, disposable datasets, caches, and packaging work on E. Do not modify the separate installed portable app or research parent as part of this plan. If investigation identifies an actual model-methodology change, scope it separately and follow the established parent-project validation process.

## Current implementation and consequences

| Area | Verified starting point | Consequence |
| --- | --- | --- |
| Exact-result reuse | `analyzer_history.py` fingerprints the full request, dataset contents, code, dependencies, and runtime. | Avoid duplicating this cache; target expensive work shared by different requests. |
| Engine execution | `analyzer_engine_runner.py` prepares a comparison and then predicts in an isolated child process. Men's preparation accepts resources; prediction supports a supplied model bundle. | Add explicit reusable boundaries while preserving isolated workers and cancellation. |
| Maintenance | `analyzer_maintenance.py` stages, hashes, audits, rebuilds, validates, and atomically promotes data. | Extend this workflow for corrections; do not build a second installer. |
| Existing fight IDs | Incremental updaters protect against duplicate existing IDs. | Corrections need a distinct replacement contract, not a relaxed append audit. |
| Training counts | Maintenance reports nonnegative rows added. | Corrections also require removed-row and signed net-change reporting. |
| Reports | Structured metrics/support notes feed native tables and exports. Recent fights are frozen into payloads. | Use the same frozen evidence for summaries and comparisons. |
| History | Up to 50 entries / 50 MB; schema 1 entries include integrity checks and calculation context. | Add backward-compatible readers and budget new provenance data. |

## Stage 0 — Establish the baseline and shared contracts

### Step 1. Record a reproducible baseline

- Create an implementation branch from the verified source; record its commit, runtime, dependency versions, model settings, dataset hashes, and free space.
- Use disposable data under `work/v05-validation` on E. Save baseline men's, women's, historical-date, sparse-history, swapped-fighter, and statistics-only outputs.
- Capture raw comparison values, final and component probabilities, warnings, recent fights, report states, and time to first comparison/completion.
- Run the existing regression suite and release audit once. Investigate failures before attributing them to new changes.
- Preserve v0.4 release evidence and `docs/NEXT_VERSION_PLAN.md` as historical records.

### Step 2. Define versioned records before connecting the UI

- Define separate schemas for computational cache manifests, correction previews, summary items, and saved-analysis comparison reports.
- Give metrics stable IDs, units, definitions, history windows, and semantic versions. Display labels alone must not establish equivalence between releases.
- Define provenance fields: stable fighter IDs, sex/model family, division, requested fight date, actual history/training cutoffs, settings, dataset fingerprints, engine/code/runtime versions, and generation time.
- Define optional frozen per-fighter history evidence: eligible fight IDs, dates, outcomes, and canonical content fingerprints needed to identify later additions/corrections. Keep it bounded and measured against the history storage limit.
- Continue reading valid schema 1 history. Verify original integrity before any in-memory adaptation. Missing provenance must display as unavailable, never be filled from today's datasets.

Deliverable: documented data contracts and test fixtures used by all four features.

## Stage 1 — Faster calculations across matchups

### Step 3. Profile both engines and choose safe cache boundaries

- Extend stage timings to separate dataset validation/hashing, parsing, dated-history preparation, fighter feature construction, model fitting, women's cross-validation/ensemble fitting, inference, and report generation.
- Measure three distinct scenarios: first calculation with empty caches; a different matchup with the same effective calculation context; and an exact repeated request served by existing history.
- Repeat representative measurements three times and report medians, peak memory, and disk footprint on the same computer. Record OS file-cache effects rather than promising a universal first-run speedup.
- Inspect dependencies at each boundary. Prove which resources, historical feature tables, fitted models, and ensemble weights are independent of the selected fighters before sharing them.
- Distinguish requested matchup date from effective training/history cutoffs. Include division or fighter-dependent inputs wherever they influence an artifact. Never reuse a whole prepared matchup for different fighters.

### Step 4. Implement a bounded computational cache

- Add `analyzer_cache.py` to own artifact manifests, keys, integrity checks, atomic writes, lookup, eviction, and clearing under `.runtime/compute_cache`.
- First cache validated parsing/feature intermediates. Then cache fitted model bundles and women's fitted components/weights only where Step 3 proves reuse is valid.
- Key each artifact by all its inputs: relevant dataset content hashes, effective cutoffs, model/configuration, feature schema, code hashes, dependency/runtime versions, and any required division or profile inputs. Do not use file timestamps as the correctness boundary.
- Persist tabular/numeric artifacts with explicit schemas. If fitted estimators require joblib or an equivalent existing serializer, restrict loading to locally generated cache artifacts with matching manifests; exclude them from downloaded datasets and release archives.
- Read/write within the existing operation-lock lifecycle. Publish only complete artifacts using temporary files and atomic replacement; cancellation must not expose partial entries.
- On corruption, incompatible versions, or a cache miss, discard that entry and calculate normally. A cache write failure must not discard a successfully computed result.
- Proposed default limit: 1 GiB, with least-recently-used eviction between operations and space checks before writes. Tune only from measured artifact sizes; cache cleanup must not touch datasets, saved analyses, or recovery backups.

### Step 5. Integrate reuse and user controls

- Wire cache lookups into both engines through explicit adapters and `analyzer_engine_runner.py`; retain current public CLI behavior when caching is disabled.
- Keep current exact-result history reuse as the first fast path. A new matchup using cached computational artifacts receives a new result and generation timestamp.
- Show truthful progress such as “Using prepared history” or “Using a compatible fitted model.” Do not replay fitting progress when no fitting occurs.
- Define **Recalculate** as bypassing both saved-result reuse and computational cache reads; it may replace valid cache artifacts after successful fresh computation.
- Add **Help → Clear calculation cache**, disabled during an active operation. Show actual cache size and explain that saved analyses remain available.
- Dataset update/restore compatibility is determined by content fingerprints. Old cache entries can remain until eviction but cannot be used for a mismatched dataset.

### Step 6. Verify correctness and performance

- Compare cache-disabled, cold-cache, and warm-cache outputs for both engines across different fighters, divisions, dates, settings, and swapped sides.
- Preserve existing baseline tolerance: final/component probabilities within `1e-12` where the existing runtime is deterministic; raw metrics, included rows, cutoff metadata, and warnings must agree. Exclude timestamps/timings from equality checks.
- Test invalidation after a dataset change, correction, restore, code/dependency change, and cutoff change. Test corrupt/truncated artifacts, cancellation, low disk space, and clear-cache behavior.
- Target at least a 50% median reduction for a different matchup in the same reusable context. Treat this as a benchmark target, not a promised result. Do not claim the milestone complete without measured benefit; revisit the cache boundary if the expensive work remains uncached.
- Investigate a median cold-run regression above 10% against the same baseline and measurements.

Primary files: `analyzer_engine_runner.py`, `analyzer_protocol.py`, `analyzer_worker.py`, `analyzer_gui.py`, both prediction engines, new `analyzer_cache.py`.

## Stage 2 — Recheck and apply corrections to recorded fights

### Step 7. Add bounded event rechecking

- Add **Help → Recheck recent events** as a separate operation; normal incremental updates retain their existing behavior.
- Default to completed events from the last 90 days, with an explicit inclusive date range and a maximum of 20 events per request. Allow older bounded ranges for older corrections. Validate dates and show the actual selected events before fetching bout details.
- If a range exceeds the cap, request a narrower range; never silently truncate and report the whole range as checked.
- Fetch fresh event and fight pages for this operation, bypassing stale scraper responses. Reuse source validation, request pacing, bounded retries, cancellation, and diagnostics.
- Identify events/fights/fighters by stable source IDs. Confirm complete event/bout captures, paired fighter rows, supported result markers, dates, and identities. Missing pages or incomplete pairs block a clean result.

### Step 8. Produce a frozen correction preview

- Add a shared `analyzer_corrections.py` contract with adapters for each engine's raw/source representation, including the women's repaired-data pipeline.
- Canonicalize typed source values so row order, whitespace, or equivalent numeric formatting do not create false corrections. Preserve meaningful missing-versus-zero distinctions.
- Classify findings as unchanged, corrected existing bout, newly discovered bout, or blocked/conflicting. Route new bouts through the existing append checks.
- Diff result/method/round/time/division/date and supported fight-stat fields. Show field-level old/new values grouped by event and bout, including whether training eligibility changes.
- Do not delete a bout just because it is absent from a response. Missing known bouts and changed identities require resolution; do not silently merge them. Profile refreshes and mass historical repairs remain outside this release.
- Save the exact staged source evidence, baseline dataset hashes, proposed replacement IDs, and preview digest in a bounded transaction. No installed data changes during preview.
- End the preview worker before enabling **Apply corrections**. Release its lock; reacquire the operation lock on apply and check that installed hashes and the preview digest still match. If anything changed, require a new preview.

### Step 9. Apply validated replacements transactionally

- Apply the captured, reviewed preview without an implicit second fetch. Audit the same captured content again before installation.
- Replace complete source records for approved existing fight IDs, including both fighter-stat rows and linked metadata. Never append corrected rows beside the originals.
- Rebuild all affected downstream features chronologically. A correction can affect later history and Elo, so rebuilding only the corrected bout is insufficient.
- For W/L → draw/NC, remove that bout's binary training examples while retaining valid source statistics. For draw/NC → W/L, generate correctly labelled examples. Keep each engine's established draw/NC Elo policy.
- Prove the women's repaired and derived inputs carry the corrected values all the way through rebuilding; do not patch only the final feature CSV.
- Extend audits for intentional replacements without weakening normal duplicate rejection. Validate expected fight IDs, fighter pairs, source uniqueness, training eligibility, and historical cutoffs.
- Report corrected bouts, added bouts, binary rows added, binary rows removed, and signed net row change separately. A no-change recheck records its checked range/time without claiming a data change.
- Use existing all-target atomic promotion, restore, and startup recovery. Errors in either selected target preserve the installed datasets for both.
- Update the catalogue and current compatibility fingerprints after commit. Already displayed and saved results retain their original contents.

### Step 10. Verify correction behavior end to end

- Fixture coverage for both engines: unchanged capture; statistic correction; corrected method/date; W/L → NC; W/L → draw; NC → W/L; mixed new and corrected bouts; malformed source; missing bout; identity conflict; repeated apply.
- Assert that unrelated source rows stay unchanged and legitimate corrections propagate to affected later features. Do not demand unchanged predictions after valid data corrections.
- Compare a corrected incremental dataset with an independently constructed, fully rebuilt expected dataset.
- Test stale previews, cancellation before commit, interrupted promotion, restart recovery, restore, and failure in the second target after the first has staged successfully.
- Run one small live recheck on a disposable copy. If the source has no real correction, record a verified no-change result; use controlled fixtures for correction proof.
- Label historical calculations as using the installed, possibly corrected source history. An event-date cutoff does not recreate what the source reported on that past day.

Primary files: both incremental updater scripts, `analyzer_maintenance.py`, `analyzer_worker.py`, `analyzer_protocol.py`, `analyzer_errors.py`, `analyzer_gui.py`, `docs/MAINTENANCE.md`, new `analyzer_corrections.py`.

## Stage 3 — Concise matchup summary

### Step 11. Specify deterministic evidence rules

- Add `analyzer_summary.py` that consumes only the frozen structured result; it makes no network calls and does not read today's dataset.
- Produce at most three observations plus up to two limitations, with stable ordering and deduplication.
- Initial rule families: UFC/division experience; recent activity/layoff; opponent-strength metrics; and supported striking/grappling differences. Use each metric's actual history window and units.
- Define a reviewed rule table with metric IDs, comparison thresholds, required observations/attempts, missing-data handling, wording, and priority. Thresholds are presentation choices, not newly validated statistical significance or model confidence.
- Prefer explicit numeric statements over unsupported adjectives. Suppress rate comparisons with insufficient support; identify prior-only estimates and missing/division-limited history as limitations.
- Do not infer causation, feature importance, certainty, or new reliability grades. Retain the existing sex-specific confidence/reliability definitions separately.
- When evidence is insufficient or differences are small, say so instead of forcing a winner-like summary.

### Step 12. Freeze and display the summary consistently

- Store `matchup_summary` with its schema/rules version, evidence IDs, values, units, windows, support, and rendered text in the report payload.
- Build it for the prepared comparison, retain it for completed prediction and cancelled/failed previews, and support statistics-only results without probability language.
- Add the summary above Overview's existing metric table, with a **View supporting metrics** action that reveals the corresponding rows.
- Render the same items in clipboard, TXT, and offline HTML exports; preserve the complete underlying report.
- Saved results reopen their frozen summary. Old entries without it remain readable and state that a summary was not saved; no silent regeneration with new rules.

### Step 13. Verify evidence, wording, and layout

- Test ties, swapped fighters, fewer than five fights, no division history, zero supporting attempts, missing fields, and differing men's/women's history windows.
- Assert every displayed claim has the correct frozen source values and units and survives save/reopen/export unchanged.
- Check all report states, small windows, large text, keyboard navigation, and normal/high DPI. Avoid color-only meaning or hidden limitations.

Primary files: new `analyzer_summary.py`, `analyzer_reporting.py`, `analyzer_results.py`, `ufc_matchup_analyzer.py`, `analyzer_gui.py`.

## Stage 4 — Compare saved versions of a matchup

### Step 14. Add a pure comparison service

- Add `analyzer_comparison.py`, accepting two validated saved records and producing a frozen comparison payload without recalculation or network access.
- Require the same sex/model family and stable fighter identities. Normalize reversed A/B order to the first record and visibly explain the alignment. If older entries lack unambiguous IDs, decline automatic alignment rather than guessing from names.
- Default to the same division and fight date. Permit different dates/divisions with a prominent context-change label and both contexts shown; this is not an isolated dataset-update comparison.
- Show probabilities before/after and deltas in percentage points, selected raw metric changes, coverage changes, and the old/new generation times.
- Show changed dataset fingerprints, app/engine/runtime versions, settings, and cutoffs as observed context differences. Never attribute a probability shift to one cause when several inputs changed.
- Compare only metrics with compatible stable IDs, units, definitions, and windows. Mark unavailable/definition-changed metrics instead of subtracting incompatible values.
- Use frozen eligible-history evidence to identify added, removed, or corrected bouts. A fight leaving the last-five panel does not prove its removal from the dataset. Older entries lacking full provenance get an explicit limitation.
- For statistics-only entries, compare available metrics and omit probability deltas. Missing probabilities must never become zero.

### Step 15. Integrate history selection and exports

- Extend **Recent analyses** with selection of two eligible entries and **Compare versions**. Explain invalid pairings inline.
- Open a read-only comparison view: context changes first, then probabilities/important metrics, then fight-history changes and full details.
- Provide **Open original**, **Open newer**, and **Save comparison TXT/HTML** actions. Do not replace or mutate either source record.
- Preserve existing 50-entry/50-MB pruning. Snapshot the selected records while a comparison is open so later pruning does not break that view or its export.
- Measure additional provenance sizes and ensure normal history remains useful within its existing cap. Do not silently increase storage limits or start retaining entire dataset copies per analysis.

### Step 16. Verify comparison compatibility and accuracy

- Test identical results; legitimate data correction; newly eligible fight; date/division change; algorithm/runtime change; reversed fighters; statistics-only versus prediction; mixed old/new schemas; ambiguous/missing identities; corrupted entries; and pruned history.
- Check raw-to-displayed deltas and rounding separately, including percentage-point units and zero-versus-missing behavior.
- Ensure all comparisons and exports work offline and preserve source generation times/provenance.

Primary files: `analyzer_history.py`, `analyzer_gui.py`, `analyzer_reporting.py`, `analyzer_results.py`, new `analyzer_comparison.py`.

## Stage 5 — Integrated validation and portable release preparation

### Step 17. Exercise the complete user journey

1. Open a fresh portable extraction on E and calculate one matchup for each engine.
2. Calculate a different matchup under the same context and record cache reuse/performance.
3. Open and export the summary; verify its evidence against the detailed metrics.
4. Recheck a bounded range on disposable data, inspect a controlled correction preview, and apply it.
5. Recalculate the original matchup and compare old/new saved results.
6. Restore the previous datasets and confirm valid-cache selection follows restored content, while old reports remain immutable.
7. Repeat with a historical date, interrupted operation, and statistics-only report.

### Step 18. Run release checks and prepare evidence

- Run existing and new meaningful regression tests, source audit, data-equipped engine checks, leakage checks, and performance benchmarks. Separate source-only CI evidence from native data-equipped validation.
- Exercise a fresh extraction, native EXE launch, offline predictions, clipboard and TXT/HTML exports, old-history compatibility, cancellation/retry/recovery, paths with spaces, and actual Windows DPI checks where available.
- Preserve and disclose unresolved clean-machine, platform, and dataset-rights limitations; do not describe an unverified gate as passed.
- Update README, maintenance/model explanations where affected, changelog, version, engine adaptation/patch manifests, package inclusion rules, and release-verification documents. Check that source export preserves the engine changes.
- Exclude caches, personal history, captured source responses, transaction logs, and local work files from source and portable archives. Record archive contents and SHA-256 hashes and verify a fresh extraction.
- Prepare source commits, release notes, portable artifacts, and a concise evidence report. Repository push and publication are a later execution step subject to the applicable user authorization; this document alone performs neither.
- If published, verify the public source CI and download the actual public artifacts to check hashes and fresh launch, rather than treating upload success as completion.

## Milestones and completion gates

| Milestone | Deliverable | Required evidence |
| --- | --- | --- |
| M0 | Baseline and shared schemas | Reproducible fixtures, timings, current regression results |
| M1 | Cross-matchup computation reuse | Both-engine parity, invalidation/failure checks, measured improvement |
| M2 | Reviewed correction workflow | Both-engine replacement/rebuild correctness, stale-preview handling, atomic rollback/restore |
| M3 | Concise matchup summary | Traceable deterministic claims, support/missing-data behavior, report/export parity |
| M4 | Saved-version comparison | Identity-safe alignment, compatible metric deltas, honest provenance limits, offline exports |
| M5 | Release candidate | Integrated journey, fresh portable verification, documented limitations and reproducible artifacts |

Implement and verify one milestone before integrating the next. Establish shared schemas early; correction provenance must be finalized before the comparison UI. The highest-risk items are correct cache dependency boundaries and correction propagation through the women's repaired-data pipeline. Resolve those with small executable proofs before broader UI work.

## Definition of done

The next version demonstrates faster new-matchup calculations without changing baseline results; safely previews and applies bounded corrections with recoverable backups; presents concise claims backed by frozen metrics; and compares saved results without guessing identities, missing values, or causes of probability changes. All four work in the fresh portable app with historical cutoffs, offline reports, compatible old history, and bounded local storage.
