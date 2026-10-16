# v0.8 application evidence and reuse contracts

All descriptive evidence is captured from the installed snapshot, separately from model features. Model policies and historical cutoffs are retained. New optional blocks use schema 1; old reports are readable without backfilling their missing evidence from current data.

## Bout details

`bout_details` contains `schema`, `history_cutoff`, `source_fingerprint` and `fighter_a`/`fighter_b`. Each side has a stable `fighter_id` and at most five recent `bouts`. Each bout retains metadata, fighter identity, available fighter/opponent statistics, duration, per-field missing/invalid reasons, pairing status and a source fingerprint. Opponent overall pre-bout Elo is copied only from an existing engine state matched by fight ID and date; otherwise it remains unavailable.

Men use raw `significant_strikes_*`, `total_strikes_*`, `takedowns_*`, knockdowns, submission attempts and control seconds. Women use the existing repaired significant-strike fields, `total_str_*`, `td_*`, `kd_landed`, submission attempts and control seconds. Missing repaired values do not fall back silently to another field. Opponent values require unique paired identity rows. Duplicated/ambiguous rows withhold affected evidence.

Duration uses a positive recorded elapsed-seconds value, or recorded minutes when elapsed seconds are unavailable. Disagreeing paired durations withhold time-based rates. Missing/invalid values remain unavailable; known zero remains zero. Landed counts greater than attempts and control time greater than duration are invalid, not clipped.

All recorded divisions and outcomes are eligible for descriptive history when event date is strictly before the selected fight date. Draws and NCs retain available statistics. Binary training rules are unchanged. Source bytes are checked before/after capture and against validated dataset fingerprints.

## Recent form

`recent_form` contains the same cutoff/provenance plus scope/note and one side record per fighter. `windows` contains `3`, `5` and `career`. Each window records actual bout count, separate result counts, covered dates, opponent context and seven versioned metrics with units, raw numerator/denominator, eligible bouts and missing bouts.

The recent window selects the most recent N recorded bouts first. Missing data do not cause older replacement bouts to be selected. Career includes all eligible UFC bouts, including the recent window. Same-day ties use fight ID because intraday chronology is not asserted.

| Metric | Formula |
| --- | --- |
| Significant strikes landed/absorbed per minute | Sum matching valid strikes / sum matching eligible minutes |
| Significant-strike accuracy | Sum landed / sum attempted |
| Takedowns per 15 minutes | 15 × sum landed takedowns / sum matching eligible minutes |
| Takedown accuracy | Sum landed / sum attempted |
| Takedown defense | 1 − sum opponent landed / sum opponent attempted |
| Control share | Sum valid control seconds / sum matching elapsed seconds |

Numerator and denominator use the same per-metric subset. Ratios pool totals; they do not average bout percentages or introduce model priors. Zero attempts produces unavailable accuracy/defense with support explaining zero attempts. Percent differences use percentage points. The UI describes recorded differences, without an automatic improvement/decline grade.

## Startup and validation caches

Interrupted dataset/import recovery completes before history is exposed. A `history_ready` worker event then allows saved reports to be viewed while live-data/dependency validation continues. Compute actions remain gated on full readiness. History compatibility is `Checking` until current fingerprints are available.

Every verified data-health call hashes current file bytes. A disposable structural-scan cache is keyed by that content hash and day, has an integrity field and a 64-file cap. It never authorizes data validity using file size/mtime alone. Missing or corrupt entries trigger a structural rescan. Validation misses verify bytes again after scanning.

The history metadata index is rebuildable and checked against each original report's current content hash. Opening a report loads and validates its full JSON. Changing original bytes invalidates indexed metadata. Calculation artifacts retain the existing content keys, storage cap and bypass semantics.

## Refresh and compare

Refresh captures an immutable original reference and defaults to the same fighters, IDs, order, division, selected date, explicit as-of setting and operation mode. Using today's date is an explicit option. It uses installed data; it does not download datasets.

Refresh bypasses saved-result lookup while allowing compatible arithmetic caches. `Recalculate` continues to bypass saved-result and arithmetic-cache reads. Manual-profile reports require their original CLI profile input; incomplete legacy requests or ambiguous identities require an explicit new matchup.

Saving a refresh protects the original from replacement/pruning while retaining the existing entry/byte budgets. If both reports cannot fit, comparison remains available transiently with a storage notice. Disabled history stays disabled. Failure/cancellation keeps the original and does not create a completed comparison entry. Navigation during work produces an Open comparison action instead of stealing the active view.

Comparisons align stable identities, respect metric semantic versions, show context/date changes and distinguish eligibility changes from changed records. They do not attribute a probability shift to one changed factor. Transient comparisons state when full saved provenance is unavailable.

## Compact export

Save report offers explicit Last 3/Last 5 compact HTML choices. The compact subset has six key metrics, three recent bouts per fighter and three recent-versus-career metrics with support. It preserves recorded probability/reliability states, dates, provenance and essential limitations. Partial/statistics-only reports have no completed prediction.

The file is self-contained, escaped, script-free and usable offline. Print targets A4/Letter at 100% with browser headers/footers off. Normal verified fixtures fit one page; long required context can use another page instead of clipping text. Detailed TXT/HTML exports retain all captured evidence regardless of which native tabs were visited.
