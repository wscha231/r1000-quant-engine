# Shakeout vs Distribution/Breakdown Study

Report-only event study. No production behavior is changed.

- events: 1353
- production_activation_allowed: `False`

## Label Counts

- `TRUE_BREAKDOWN`: 141
- `DISTRIBUTION`: 450
- `AMBIGUOUS`: 325
- `SHAKEOUT`: 437

## Label Medians

| Label | N | Median DD | Median 6m Return | Recovery 6m | Half Recovery 6m | Lower Low After Half | Shakeout Quality | Distribution Risk | Breakdown Risk |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| AMBIGUOUS | 325 | -12.95% | 10.23% | 68.00% | 79.69% | 2.77% | 0.618 | 0.327 | 0.150 |
| DISTRIBUTION | 450 | -12.88% | -1.01% | 61.56% | 92.00% | 90.67% | 0.545 | 0.545 | 0.200 |
| SHAKEOUT | 437 | -13.01% | 36.47% | 100.00% | 100.00% | 9.84% | 0.800 | 0.273 | 0.000 |
| TRUE_BREAKDOWN | 141 | -13.10% | -17.56% | 3.55% | 7.80% | 0.00% | 0.436 | 0.318 | 0.370 |

## Best Event-Level Actions By Label/Horizon

| Label | Horizon | Best Action | N | Median Return | Hit Rate |
|---|---|---|---:|---:|---:|
| AMBIGUOUS | 1m | add25 | 325 | 0.28% | 50.77% |
| AMBIGUOUS | 3m | add25 | 325 | 6.17% | 66.77% |
| AMBIGUOUS | 6m | add25 | 325 | 12.79% | 85.85% |
| DISTRIBUTION | 1m | add25 | 450 | 3.24% | 63.11% |
| DISTRIBUTION | 3m | add25 | 450 | 1.18% | 53.33% |
| DISTRIBUTION | 6m | exit_to_cash | 450 | 0.00% | 0.00% |
| SHAKEOUT | 1m | add25 | 437 | 7.30% | 73.68% |
| SHAKEOUT | 3m | add25 | 437 | 22.06% | 91.53% |
| SHAKEOUT | 6m | add25 | 437 | 45.59% | 100.00% |
| TRUE_BREAKDOWN | 1m | exit_to_cash | 141 | 0.00% | 0.00% |
| TRUE_BREAKDOWN | 3m | exit_to_cash | 141 | 0.00% | 0.00% |
| TRUE_BREAKDOWN | 6m | exit_to_cash | 141 | 0.00% | 0.00% |

## Recent / Largest Events

| Ticker | Event | Label | DD | Fwd 6m | Recovery 6m | Half Recovery 6m | Lower Low | Quality | Dist Risk | Breakdown Risk |
|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|
| LRCX | 2025-11-18 | SHAKEOUT | -13.90% | 111.60% | 1 | 1 | 0 | 0.909 | 0.164 | 0.000 |
| FLEX | 2025-11-18 | SHAKEOUT | -12.90% | 127.67% | 1 | 1 | 0 | 0.909 | 0.164 | 0.000 |
| AMD | 2025-11-18 | DISTRIBUTION | -12.88% | 95.23% | 1 | 1 | 1 | 0.818 | 0.436 | 0.100 |
| TER | 2025-11-18 | SHAKEOUT | -12.72% | 116.22% | 1 | 1 | 0 | 0.909 | 0.236 | 0.100 |
| NVDA | 2025-11-18 | SHAKEOUT | -12.40% | 21.05% | 1 | 1 | 1 | 0.727 | 0.364 | 0.000 |
| AMZN | 2025-11-18 | SHAKEOUT | -12.38% | 20.63% | 1 | 1 | 1 | 0.818 | 0.364 | 0.000 |
| QCOM | 2025-11-18 | DISTRIBUTION | -12.05% | 30.79% | 1 | 1 | 1 | 0.909 | 0.436 | 0.100 |
| COHR | 2025-11-13 | SHAKEOUT | -16.04% | 159.22% | 1 | 1 | 0 | 0.909 | 0.236 | 0.100 |
| TSLA | 2025-11-13 | DISTRIBUTION | -14.17% | 1.99% | 1 | 1 | 1 | 0.727 | 0.436 | 0.100 |
| MTZ | 2025-11-13 | SHAKEOUT | -14.13% | 102.85% | 1 | 1 | 0 | 0.909 | 0.164 | 0.000 |
| JBL | 2025-11-13 | SHAKEOUT | -13.92% | 67.99% | 1 | 1 | 0 | 0.691 | 0.382 | 0.150 |
| VRT | 2025-11-12 | SHAKEOUT | -13.00% | 114.09% | 1 | 1 | 1 | 0.818 | 0.364 | 0.000 |
| PLTR | 2025-11-06 | DISTRIBUTION | -15.51% | -21.80% | 0 | 1 | 1 | 0.436 | 0.636 | 0.520 |
| HD | 2025-11-06 | TRUE_BREAKDOWN | -12.84% | -14.51% | 0 | 0 | 0 | 0.255 | 0.518 | 0.390 |
| SYK | 2025-11-06 | DISTRIBUTION | -12.12% | -19.72% | 0 | 1 | 1 | 0.164 | 0.836 | 0.640 |

## Next Gate

Use these event labels to train/validate a hold/add/trim/exit policy,
then run a true portfolio-level challenger replay before production activation.
