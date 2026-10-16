# UI polish implementation plan

Status: implemented locally. See `UI_POLISH_VERIFICATION.md` for verification and remaining physical-display checks.

Prepared: 15 October 2026. Baseline: the current local v0.7 interface and screenshots.

## Objective and scope

Implement all six proposed improvements: a prominent matchup panel, a structured Overview, simpler controls, clearer charts, consistent visual styling, and polished everyday interactions. Keep the existing Windows Tkinter/ttk application and single-matchup workflow.

This is a presentation and interaction change. Existing prediction values, evidence semantics, saved-result compatibility, calculation reuse, maintenance transactions, and exports must remain trustworthy. Initial and statistics-only comparisons must never acquire a winner, probability, or reliability claim. Preserve the limitations captured in each saved result; do not substitute current validation findings into an older report.

## 1. Record the baseline and define the state matrix

1. Review the working-tree changes and any applicable repository instructions before editing. The checkout already contains substantial v0.7 work; record its state and preserve those edits.
2. Capture the current Overview, Statistics, Charts, Recent fights, and Report views using existing frozen fixtures. Use temporary preferences/history so review does not change the user's saved settings.
3. Record representative window dimensions, text size, and source fixture for each capture so before/after comparisons are reproducible.
4. Inventory existing commands, shortcuts, enabled-state rules, text preferences, and result states.
5. Prepare representative fixtures for: empty startup; initial comparison; advanced comparison while training; complete prediction; statistics-only completion; cancelled or failed prediction with partial evidence; reopened result; stale inputs; incompatible saved result; older report with missing evidence; maintenance in progress; and viewing an older report while a new calculation finishes.
6. Include both model families, accented/long names, missing values, zero values, extreme probabilities, and sparse histories. Use synthetic fixtures for display edge cases and label them as such.

Acceptance: every currently supported user workflow has a baseline and an explicit expected display state. Fixture loading requires no model retraining or dataset downloads.

## 2. Establish the shared visual foundation — recommendation 5

1. Add a small `analyzer_theme.py` module for shared color, font, spacing, border, and control-style definitions.
2. Define semantic colors for application background, content surface, primary/secondary text, borders, selection, focus, warnings, errors, primary actions, and the two fighter roles.
3. Use a light neutral background, white content surfaces, dark text, and restrained blue/orange fighter accents. Fighter colors identify sides rather than good/bad outcomes. Assign the same colors to names, probability segments, table headers or adjacent markers, and charts.
4. Keep Segoe UI for the interface and Consolas for the plain-text report. Define title, section heading, body, caption, and probability sizes derived from the existing Small/Medium/Large preference.
5. Standardize spacing around a small scale, such as 4/8/12/16/24 logical units. Prefer font metrics and content-driven geometry over rigid widget heights.
6. Define reusable ttk styles for primary and secondary buttons, tabs, panels, table headings, rows, and warning labels. Verify what the selected Windows ttk theme actually renders before relying on custom background colors.
7. Retain standard keyboard behavior and clear focused, selected, disabled, and pressed states. Measure text contrast and check the fighter colors on white surfaces; color must always have accompanying names or labels.
8. Apply the same styles to relevant dialogs, suggestions, calendar, history, and maintenance views, with restrained changes to their structure.

Acceptance: all main tabs and dialogs share typography and spacing; text-size preferences cover labels and controls as well as textboxes and tables; meaningful focus remains visible.

## 3. Replace positional UI references before moving commands

1. Give tabs stable references or semantic keys and use them for navigation. Remove dependencies on tab positions in application code, tests, and capture utilities.
2. Replace numeric Help-menu indexes with a command registry containing each command's menu, entry reference, callback, and enabled-state rule.
3. Inventory every command before moving it: update, recheck, restore, rebuild, installation check, diagnostics, cache clearing, model validation, import, undo import, and history storage preferences.
4. Keep one central function responsible for applying command states from existing readiness, busy, cancellable, backup, and import state.
5. Add or adapt focused behavior checks to ensure moving a menu entry cannot accidentally enable a destructive or conflicting action.

Acceptance: changing menu order or tab order does not change the action invoked or its availability. Existing operation exclusion and cancellation restrictions remain intact.

## 4. Build the prominent matchup panel — recommendation 1

1. Replace the combined summary paragraph with a reusable matchup-result panel, using a focused widget in `analyzer_widgets.py` or a dedicated small presentation module if that keeps the file readable.
2. Show two clearly labelled fighter areas with full names and prominent percentages for completed predictions. Place division and fight date directly beneath or above the paired result.
3. Display the model's recorded pick with the label `Model prediction`, retaining its uncertainty context. Avoid styling a forecast as a recorded fight outcome.
4. Reuse the fighter colors from the theme in the probability bar. Place names and percentages outside narrow segments so a 99%/1% result cannot clip a label.
5. Give reliability its own labelled line. Preserve the distinction between probability stability and outcome certainty, including any explicit unvalidated status.
6. Render result variants explicitly: partial evidence, training in progress, statistics only, cancelled, failed, and complete. Clear previous percentages when transitioning into a state without predictions.
7. Show saved/reused and generated-time information as secondary metadata. Keep the displayed report's identity separate from editable inputs.
8. Reflow or stack the fighter areas when available space or large text demands it; preserve full names through wrapping or an accessible full-name detail.

Acceptance: users can immediately identify the fighters, date, division, result mode, and probabilities when available. Long names and extreme percentages remain legible, and partial results never display stale probabilities.

## 5. Restructure the Overview — recommendation 2

1. Organize the view into Prediction, Evidence quality, and Key statistics, with consistent section headings and spacing.
2. Replace the four-line scrolling evidence textbox with labelled fields built from the existing frozen `evidence_quality` record.
3. Present each fighter's eligible UFC bouts, selected-division bouts, and latest included bout alongside shared dataset date and evaluation compatibility.
4. Keep methodology status, limited evaluation evidence, insufficient history, and data/evaluation mismatch visible when applicable. Do not condense distinct findings into a single reassuring badge.
5. Keep `Evidence details` for longer definitions, support information, and methodology explanations. Do not infer attempt denominators from fight counts.
6. Give captured matchup observations a separate short section where available, retaining the route to their supporting metrics.
7. Preserve all twelve existing key statistics. Improve row padding, numeric alignment, units, headings, and neutral difference formatting rather than choosing new metrics in this UI pass.
8. Avoid competing small scroll regions. Prefer a single outer Overview scroll area when content exceeds the viewport, with carefully routed mouse-wheel and keyboard scrolling. Detailed Statistics can retain its own table scrolling.
9. Render old reports gracefully with explicit `Not recorded in this saved analysis` values where evidence is absent. Do not fill their gaps from current datasets.
10. Update capture code that currently manipulates `evidence_text` directly.

Acceptance: key evidence can be scanned without scrolling a tiny textbox; important limitations remain visible; every prior statistic and explanation remains reachable.

## 6. Simplify controls and menus — recommendation 3

1. Make Analyze the primary command while matchup inputs are open. Keep Compare statistics only as a clearly labelled secondary command.
2. When results are shown with collapsed inputs, emphasize Edit matchup and report actions. Keep Recalculate available with its existing bypass-reuse behavior and an explanatory tooltip or nearby help text.
3. Group Copy report and Save report together. Keep TXT and HTML choices inside Save report and preserve existing shortcuts.
4. Keep Recent analyses easy to reach. Move text size to a discoverable View menu while retaining Ctrl+Plus/Minus and saved preferences.
5. Create Data & maintenance for update, recheck, restore, rebuild, installation checks, diagnostics, cache management, import, and undo. Use separators to distinguish datasets, application maintenance, and migration.
6. Keep Help focused on instructions and model/methodology information. Place history-storage preferences with history/settings, ensuring they remain discoverable.
7. Show Cancel only during an active operation. Enable it only while the controller permits cancellation; explain the non-cancellable installation stage without implying it can be interrupted safely.
8. Reuse the existing callbacks and operation controller. Do not duplicate maintenance logic in menu handlers.

Acceptance: a clear primary action is apparent in each main state; all existing actions remain reachable; busy and backup-dependent rules still work from the new menus.

## 7. Improve chart readability — recommendation 4

1. Add a persistent legend with fighter names above the paired metric charts and a matching legend for the Elo view. Use the same colors throughout the application.
2. Replace unexplained A/B labels where space permits; where shorthand is necessary, retain a visible name mapping.
3. Group paired metrics by their existing subject categories, with consistent spacing and readable values. Keep percentage axes at 0–100% and other paired bars on a shared zero-based scale within each metric.
4. Display metric-direction guidance only where the existing definition supports it, such as `Lower is generally preferable` for strikes absorbed. Leave contextual measurements neutral.
5. Distinguish unavailable values from actual zero. Do not render missing data as a zero-length performance bar.
6. Add Elo y-axis tick labels, restrained gridlines, and x-axis bout-number ticks. Label the horizontal axis `Successive recorded bouts`; each fighter's nth bout is not necessarily on the same date.
7. Preserve pre-bout rating conventions, frozen evidence, and the existing data cutoff. Handle single-point and missing-history cases explicitly.
8. Improve point inspection using existing saved fields: bout number, date when recorded, fighter, and rating. Keep the same information accessible in a selectable numeric view so pointer hover is optional.
9. Make chart captions and labels respond to the text-size preference and available width.
10. Check HTML chart presentation for matching fighter colors, legends, units, and axis meaning. Preserve complete TXT/HTML evidence and all numerical values; no history rewrite is required for styling.

Acceptance: charts identify both fighters and units without consulting another tab, distinguish missing from zero, and cannot reasonably be mistaken for a shared calendar timeline. Displayed values match the frozen report.

## 8. Polish navigation, timestamps, and feedback — recommendation 6

1. Order tabs as Overview, Statistics, Charts, Recent fights, Report. Update labels, help text, and navigation targets together.
2. Format valid generated timestamps as readable dates and times with an explicit timezone. Use the user's local timezone for the UI and retain original stored timestamps. Treat the selected fight date as a date, without timezone conversion.
3. Provide explicit fallbacks for missing, invalid, or timezone-naive timestamps; never silently invent an offset.
4. Hide the idle progress indicator and show it only during work. Use an intentional operation area so visibility changes do not cause distracting layout jumps.
5. Continue showing actual stage names and elapsed time. Show numerical progress only for stages that supply genuine completed/total values.
6. Preserve visible stale-result, reused-result, failed, cancelled, and new-result-ready messages. Keep copy/export clearly tied to the displayed report.
7. Review empty states and inline errors so each identifies the next available action. Preserve entered fighter names and date after validation errors.
8. Verify Tab/Shift+Tab, arrow-key selection, Enter/Escape, Ctrl+Enter, Ctrl+F, Ctrl+S, report copy, and text-size shortcuts. Do not steal focus during progress updates or report rendering.

Acceptance: navigation uses the new labels consistently, time displays are readable and unambiguous, and idle/running/completed states are visibly distinct without misleading progress.

## 9. Integrate layout and regression checks

1. Extend existing GUI tests for meaningful behavior changes: result-state transitions, probabilities disappearing in partial views, menu enablement, stale-report handling, timestamp fallbacks, and missing chart values.
2. Update `tools/check_layout.py` to inspect only intentionally visible widgets and explicitly test the states where hidden controls should appear. Do not merely remove checks for moved controls.
3. Run simulated Tk scaling at 100%, 125%, 150%, and 200%, with Small/Medium/Large text, expanded and collapsed inputs, default and minimum window dimensions, and maximized layout.
4. Capture and inspect every main tab plus representative history, evidence, calendar, and maintenance dialogs. Verify content boundaries, readable labels, focus, scroll access, and no overlapping controls.
5. Check a 1366×768 laptop-sized viewport where available, and verify larger monitors do not create unnecessarily stretched text or charts. At high scaling, provide accessible scrolling rather than shrinking text to fit.
6. Run the relevant GUI, evidence, visual/export, history, and maintenance workflow checks, then the repository's required regression checks. Reuse existing fixtures; do not retrain every model for presentation-only verification.
7. Compare representative saved payloads before and after UI rendering and confirm probability, evidence, timestamps, fingerprints, and history records were not changed by display code.
8. If the new theme/presentation modules affect import inventories or packaging allowlists, update those through the established tooling and smoke-test an isolated candidate package. Do not overwrite existing release evidence or publish from this task.
9. Separately perform actual Windows display-scaling checks at 100%, 150%, and 200% when available. Label Tk simulation and physical display checks separately; leave unperformed checks explicitly outstanding.

Acceptance: the six improvements pass their behavior checks and visual inspection; required regressions pass; any remaining real-display verification is accurately documented.

## 10. Finish documentation and handoff

1. Refresh screenshots and README instructions to match tab names, menus, buttons, and evidence placement.
2. Record a concise verification report listing fixtures, tested states, window sizes, text sizes, scaling method, results, and remaining limitations.
3. Provide before/after images of Overview and Charts, plus a compact summary of the other four improvements.
4. Review the final diff for accidental changes to model code, datasets, saved histories, or existing v0.7 release artifacts.

Completion requires all six improvements, reachable existing functions, preserved result semantics, verified keyboard use, and documented visual checks. A new color scheme alone is not completion.

## Main file map

| File | Planned role |
| --- | --- |
| `analyzer_gui.py` | Layout, result rendering, navigation, menu registry, operation states, resizing |
| `analyzer_widgets.py` | Reusable result/evidence presentation widgets and shared widget behavior |
| `analyzer_theme.py` (new) | Shared colors, typography, spacing, and ttk styles |
| `analyzer_visuals.py` | Legends, axes, metric direction, missing values, accessible numeric presentation, HTML chart styling |
| `analyzer_evidence.py` | Existing frozen evidence semantics; add presentation helpers only if needed |
| `analyzer_results.py` / `analyzer_reporting.py` | Verify export compatibility; change presentation only where justified |
| `tests/test_gui.py` and relevant existing tests | Behavioral regression coverage |
| `tools/check_layout.py` | Visible-state geometry, scaling, focus, and layout checks |
| `tools/capture_v07_overview.py` | Remove tab-index/textbox assumptions and capture revised views |
| `README.md`, `docs/images/`, new UI verification note | User guidance and review evidence |

## Suggested implementation checkpoints

1. Baseline captured; style foundation and stable command/tab references ready.
2. Matchup panel and Overview complete, with partial/saved-result states verified.
3. Toolbar, menus, navigation, and operation feedback complete.
4. Charts and remaining typography/dialog polish complete.
5. Regression checks, visual inspection, package smoke check where applicable, and documentation complete.

Each checkpoint should include a small reviewable diff, the relevant screenshots, and the checks performed. Record progress so implementation can resume without repeating completed verification.
