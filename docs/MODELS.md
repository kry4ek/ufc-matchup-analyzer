# Model notes

Men's public default is **v3_bayes_smoothed**: the retained regularized logistic model with v2 baseline/Elo/debutant features and additional Bayesian rate differences. It retains C=0.10 and the registered 0.90 probability shrinkage. V2 data remains necessary because v3 live strength estimation depends on it.

Women's public default is **v1_current_ensemble**: the retained advanced predictor using repaired statistics, prefight Bayesian smoothing, calibrated component models, and its existing ensemble weighting. Experimental women versions and full-card policy overrides are excluded.

The public adapter selects the intended version explicitly and gives both routes a consistent interface. Successful engine calculations, calibration and features are preserved. An infrastructure failure during women's cross-validation now stops prediction with a diagnostic error: it cannot silently replace the ensemble's validated weights. The small-sample policy remains unchanged. Engines train locally when invoked; downloaded model binaries are unnecessary.

## Preparation, predictions and saved results

Both engines prepare the dated snapshots, Elo, report metrics, Bayesian inputs and forward/reverse feature rows once. A prediction uses this prepared object for its existing model fitting, calibration and ensemble policies. A statistics-only comparison stops before prediction fitting; it has no probability, winner, confidence or reliability assessment. Preparation may itself be expensive, especially men's advanced strength features. Cancelling after preparation leaves a labelled comparison available for copying/exporting, but does not save a completed prediction.

Saved-result reuse requires full dataset integrity verification and an exact request/context fingerprint: canonical identities and order, division, dates and effective cutoff, worker mode, profile contents, model/application code and runtime dependency versions. Reuse preserves the original generation time. Recalculate bypasses reuse and calculation-cache reads. Source CLI predictions remain fresh by default; `--use-cache` opts into saved-result reuse. Compatible fitted models and prepared histories are serialized as bounded local calculation artifacts introduced in v0.5; they are never distributed or imported from previous installations. Individual validation, loading, feature preparation, cross-validation, training and rendering timings are recorded where measured.

Coverage notices describe strictly earlier recorded UFC fights. They do not redefine the engines' confidence/reliability rules. A division Elo of 1500 with no division history is a baseline, and a Bayesian rate with zero attempt support is prior-only. A−B and the metric's general direction describe statistics, not the model's reasoning or a guaranteed advantage.

## Dates and identity

For future men's matchups, training ends at today's available data. For a matchup dated today or earlier, the public interface uses the preceding day as its maximum training cutoff. An explicit men's as-of date can be earlier. Later rows can remain in the source CSV but are excluded from the fit. Women's training and live Bayesian history use event_date strictly before fight-date.

Date and identity rules matter more than an apparently strong probability. Unknown or ambiguous fighter names are rejected with suggestions rather than selected automatically. Use the displayed UFCStats ID to distinguish men with identical names. Women's IDs can verify a unique canonical name, but the retained engine matches names; duplicate women's identities are rejected even if an ID is supplied, until the source identity is repaired.

Manual profiles are opt-in. Use a CSV with `fighter,height_cm,reach_cm,stance,date_of_birth` (DOB in YYYY-MM-DD form). Include exact names. Missing history remains missing: supplied measurements do not create non-UFC fight history. Predictions involving such fighters must be interpreted as low-information estimates.

## Detailed comparison report

The report reads the exact dated live snapshots and feature rows already computed by the selected engine. Reporting adds JSON fields; it does not retrain differently, change calibration or mix today's fight statistics into historical results. `fighter_a_comparison` and `fighter_b_comparison` supplement the legacy snapshots. Women's JSON also exposes `model_weights`, `model_predictions`, `reliability_factors` and the complete `reliability_notes`.

Overall and division Elo start at 1500 with K=32; these are internal ratings, not official rankings. A division baseline can mean no division history. Men's base opponent-Elo average uses up to five decisive fights; the advanced refined average covers all history and the recent average covers the latest three. Women's opponent-Elo average covers prior recorded fights. Men's strongest opponent means faced; women's best-win opponent means defeated. Recent Elo change uses the engine's stored rating states, rather than a newly defined performance score.

Rates come from the engine's available UFC history, using its time normalization. They may differ from UFCStats profile averages. Percentages are displayed as percentages, with A−B in percentage points. Control is seconds per 15 minutes. Recent windows use up to three or five available fights. Missing values remain N/A, including method histories with incomplete source coverage. Known five-round experience may be a lower bound.

Men's Bayesian comparison shows the four selected rate-strength variants, excluding the unused SEB diagnostic candidate. Women's Bayesian opponent accuracy allowed means opponents' success rate (lower is better), while defense means prevention (higher is better). Attempt denominators measure support; zero support can yield a prior-only estimate. Women's opponent-Elo-weighted performance is a weighted average of fight differentials, not a calibrated win probability.

Fight history and Bayesian priors obey the analysis cutoff. Physical profile measurements can reflect later source corrections, so they are not guaranteed to be the measurement published on the historical date. Results are immutable: the window, clipboard and TXT export use the same complete report after later input changes.

The Recent fights panel reads raw recorded bouts, deduplicates by fight/fighter identity and selects at most five with `event_date < fight_date`. Draws and no-contests appear with textual results even though they do not supply binary training labels. All divisions are included. Date ties use a stable fight-ID order without claiming within-day chronology. Missing metadata remains N/A. The men's optional earlier model-training cutoff is distinct from this displayed history date. Each saved analysis retains its captured list; older reports without one are not backfilled from current datasets.

The review baseline included successful real predictions for both routes, men’s dataset integrity checks, and a sampled v3 parity test covering 20 fights and 10,800 comparisons without mismatches or same-date/target-fight leakage. Release-specific checks and results are in `RELEASE_VERIFICATION.md`.

Passing engineering checks is not evidence of guaranteed accuracy or profitability. Estimates can be overconfident, data can be incomplete, UFC history can be sparse, and changing fighter conditions are not fully captured. Women's reliability evaluates stability and support, not whether a fight is predictable. No live odds feed or full-card workflow is included.

The [v0.6 dated evaluation](MODEL_VALIDATION.md) scored all 24 supported decisive bouts in its two-date scope, with no failed or remaining calculations. Its frozen final holdout contains nine men and three women bouts, so aggregate scores are descriptive. The women ensemble's shuffled ungrouped folds overlap mirrored bout pairs; internal calibration also uses ungrouped stratification. This defect affects model-weight/calibration methodology and remains unresolved. The outer chronological evaluation excludes the selected date and later training rows, but does not clear the internal methodology gate. Algorithm corrections require a separate parent research cycle and new evaluation.

Visual comparison stores metric values and actual engine pre-bout Elo states with each new report. Men use the stored decisive-bout series, women the prepared live series. These histories follow the selected-date exclusion; division columns refer to each recorded bout's division. Older reports show only their saved metrics, without regenerating Elo from current datasets. Legacy rate attempt denominators are unavailable and are labelled separately from eligible bout counts.
