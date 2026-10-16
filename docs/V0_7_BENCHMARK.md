# v0.7 men's latency benchmark

The parent numeric conversion fast path handles existing numeric scalars
directly and retains the generic parser for other inputs. Model policy,
features, calibration, shrinkage and reported metrics remain unchanged.

Three alternating reference/candidate fresh requests used the same machine,
Python 3.14.7, locked dependencies and September datasets, without competing
evaluation jobs. Saved-result and calculation-cache reads were bypassed.
OS file caches were not controlled; this is not a cold-boot benchmark.

| Request seconds | Repetition 1 | Repetition 2 | Repetition 3 | Median |
| --- | ---: | ---: | ---: | ---: |
| Reference | 87.072 | 90.720 | 91.413 | 90.720 |
| Optimized | 52.805 | 48.412 | 50.851 | 50.851 |

The representative median fell by 43.95%. Probabilities and raw metrics agree
within 1e-12. Separately, 75 scalar/default cases and every fighter history at
2000-01-01, 2020-01-01 and 2026-10-10 matched the original implementation.

This is a measured improvement for the affected men's route, not a uniform
promise for all matchups. The refreshed October portable matrix records actual
functional timings separately. Women's calibration policy changed, so its
before/after timings are not a comparison of identical model semantics.
