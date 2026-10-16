# v0.7 research protocol

Registered on 15 October 2026 before final-test scoring. Candidate model policy:
`v2_chronological_calibrated_ensemble`. Split policy:
`event-date-expanding-3_calibration-latest-20pct-v1`.

The cohort covers 27 September 2023 through 26 September 2026. Development ends
26 September 2025; the later period is reserved for final evaluation in this
cycle. The already scored v0.6 dates, 19 and 26 September 2026, are retained as
explicit exposure accounting and excluded from the new final-test claim. Prior
research exposure beyond those dates is not independently established, so all
results remain limited retrospective evidence.

| Family | Development bouts / dates | Final-test bouts / dates | Previously exposed bouts |
| --- | --- | --- | --- |
| Women | 165 / 76 | 72 / 34 | 4 |
| Men | 824 / 83 | 454 / 42 | 20 |

Score one decisive outcome per bout, orient by stable fighter identity, and
exclude all same-date/later training information. Retain mirrored rows together
in weighting, fitting, and calibration. Baselines are the frozen current model
policy, 50/50, and unmodified pre-bout Elo expectations. Men's production model
remains the v3 logistic model with its registered 0.90 shrinkage.

Primary metric: log loss. Also report Brier score, accuracy, fixed five-bin
calibration with counts, paired event-date uncertainty where supported, and
complete failure/exclusion accounting. Candidate material-regression margins
are +0.025 log loss and +0.015 Brier versus the frozen reference. The women's
final cohort must contain at least 50 scored bouts and 20 event dates. These
counts are coverage gates, not proof of statistical independence or accuracy.
Methodology, complete coverage, reproducibility, and acceptable performance are
separate promotion gates. No tuning against final-test results.

The first stored-row pilot revealed a recent debutant's profile inputs differed
from current dated app preparation. Earlier diagnostic protocol records remain
preserved. The current protocol evaluates women's parent models on actual
dated public-app forward/reverse input rows, retaining the installed training
snapshot. Later profile corrections remain disclosed. The men's broader
stored-row evaluation requires independent live parity checks before any claim
that it describes complete app behavior.

The runner registers exact code/data/dependency signatures before scoring.
It saves per-event forecasts, start/finish attempt records, and checkpoints;
changed inputs require a new run. Raw forecasts, attempts, local paths, and
machine-specific evidence remain in private work directories. Reviewed public
aggregates must include completed counts, uncertainty limits, methodology
audits, exposure limitations, and the precise evaluation scope.

Performance benchmarks compare identical model policies and datasets. Their
provisional objective is a 20% improvement in median fresh-prediction latency
on the affected route, without numerical changes. Profiling already identified
repeated single-value pandas Series construction in men's history conversion
as a substantial preparation cost. The parent optimization preserves generic
parsing and applies a direct path only to existing numeric scalars.

Legacy women's reliability thresholds are not promoted as validated ratings
under the corrected policy. The app retains their captured values for provenance
while displaying that the assessment is unavailable for the new policy.
