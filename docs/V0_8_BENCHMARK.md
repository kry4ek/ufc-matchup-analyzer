# v0.8 performance measurements

All values are measured on the available computer with the same bundled runtime and matching data. Fresh computations bypass saved-result and calculation-cache reads. OS file caches and unrelated system load were not controlled; these are not cold-boot claims. Three alternating pairs support medians and observed ranges, not reliable tail-percentile claims.

| Journey | Reference median (s) | Candidate median (s) | Change | Reference range | Candidate range |
| --- | ---: | ---: | ---: | --- | --- |
| startup-men | 10.035 | 3.835 | 61.8% faster | 8.183–13.305 | 3.747–5.492 |
| compare-men | 56.649 | 33.789 | 40.4% faster | 51.015–57.983 | 31.633–64.234 |
| compare-women | 9.744 | 10.241 | 5.1% slower | 9.367–11.134 | 9.901–10.303 |
| predict-men | 59.063 | 51.328 | 13.1% faster | 55.580–67.296 | 38.844–60.467 |
| predict-women | 31.472 | 30.975 | 1.6% faster | 28.188–33.818 | 30.385–32.362 |

Positive change means lower latency. Any negative change is a slowdown, not an improvement. The full raw run list is retained in `verification_evidence.json` and the local work evidence. The first startup set overlapped the native regression suite; an idle rerun, when present, replaces it in this table. Startup includes dependency imports and compute-readiness checks, while saved-report availability and first visible window are separate interactions.

The original targets were at least 25% lower startup/comparison medians when the baseline exceeded five seconds, no reproducible full-prediction regression over 5%, and responsive native interactions. Targets are reported honestly: the women’s statistics-only route did not show the requested 25% gain in the first complete set. No model policy or comparison field was removed to manufacture a timing result.

The row-iteration optimization was made in the research parent first. Every base and advanced fighter history, global/division total and identity mapping agreed at three dated cutoffs before export. The first dictionary-conversion variant preserved values but was slower; it was retained locally and replaced before promotion. End-to-end benchmark PASS requires unchanged raw comparison values and probabilities within 1e-12.

Near-capacity history: 52,103,900 bytes across 50 entries; opening the dialog returned in 0.011 s; selected report opened in 0.349 s. Maximum observed event-loop gap during loading was 0.114 s.
Native bout expansion ranged 0.122–0.278 s; recent-window changes 0.025–0.050 s. Values include layout processing; cases over the 150 ms planning target remain visible in the evidence.
The actual native EXE showed its first window in 1.872 s and became compute-ready in 13.805 s in the final package check. These individual observations are separate from the repeated startup benchmark and include the available machine's load/library/file-cache conditions.
