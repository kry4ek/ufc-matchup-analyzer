# v0.7 model decision

Decision: promote `v2_chronological_calibrated_ensemble` with limited
retrospective evidence. Keep men's `v3_bayes_smoothed` unchanged.

| Gate | Evidence |
| --- | --- |
| Methodology | 110 women's event dates; 1,650 disjoint nested boundaries; complete preprocessing fits only on each fitting block |
| Complete accounting | Women 165 development + 72 final; men 824 + 454; no failed or remaining cases |
| Development | Candidate log loss 0.662262 / Brier 0.235013; reference 0.660831 / 0.234196; within registered margins |
| Final cohort | Candidate log loss 0.613053 / Brier 0.212020; reference 0.627314 / 0.217864; fixed +0.025 / +0.015 margins passed |
| Parent/export | Both families agree within 1e-12 on the refreshed snapshot; women's fold audits also match; development-period debut and synthetic manual-profile cases pass |
| Failure behavior | Insufficient history preserves the available comparison, invents no probability, and creates no completed history entry |
| Integration | Explicit policy provenance, cache separation, preserved old results, no inherited women's numerical reliability grade |

Final women's accuracy was 49/72 (68.1%) versus 47/72 (65.3%) for the reference.
The paired event-date log-loss interval is approximately [-0.0359, 0.0079],
including zero. These observations do not establish a statistically significant
improvement, prospective performance, or profitability. Repeated fighters and
later profile/source corrections limit interpretation.

The final cohort was opened only after complete development review; model
settings were unchanged. Previously scored v0.6 dates are excluded, while prior
research exposure beyond those dates is not independently established.

The evaluated September snapshot remains separate from the current installation
through 10 October. Its hashes are not replaced with the refreshed hashes in
the report. The app therefore shows a data mismatch while preserving the
methodology audit. Exact aggregates and provenance are in
[the model report](MODEL_VALIDATION.md); the old
[v0.6 report](MODEL_VALIDATION_V06.md) remains unchanged.

This decision permits local v0.7 assembly. It does not publish the app or clear
clean Windows, actual display-scaling, dataset-rights or signing limitations.
