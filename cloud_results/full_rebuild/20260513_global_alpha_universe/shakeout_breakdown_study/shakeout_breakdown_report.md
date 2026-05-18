# Shakeout vs Distribution/Breakdown Study

Report-only event study. No production behavior is changed.

- events: 1298
- production_activation_allowed: `False`

## Label Counts

- `DISTRIBUTION`: 434
- `TRUE_BREAKDOWN`: 131
- `AMBIGUOUS`: 328
- `SHAKEOUT`: 405

## Label Medians

| Label | N | Median DD | Median 6m Return | Recovery 6m | Half Recovery 6m | Lower Low After Half | Shakeout Quality | Distribution Risk | Breakdown Risk |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| AMBIGUOUS | 328 | -12.87% | 9.96% | 68.29% | 80.18% | 2.74% | 0.609 | 0.327 | 0.150 |
| DISTRIBUTION | 434 | -12.86% | -1.14% | 57.83% | 89.63% | 87.10% | 0.545 | 0.545 | 0.200 |
| SHAKEOUT | 405 | -13.11% | 36.12% | 100.00% | 100.00% | 10.62% | 0.800 | 0.273 | 0.000 |
| TRUE_BREAKDOWN | 131 | -13.14% | -17.56% | 3.05% | 6.11% | 0.00% | 0.436 | 0.318 | 0.370 |

## Best Event-Level Actions By Label/Horizon

| Label | Horizon | Best Action | N | Median Return | Hit Rate |
|---|---|---|---:|---:|---:|
| AMBIGUOUS | 1m | add25 | 328 | 0.31% | 50.61% |
| AMBIGUOUS | 3m | add25 | 328 | 7.39% | 67.68% |
| AMBIGUOUS | 6m | add25 | 328 | 12.45% | 84.45% |
| DISTRIBUTION | 1m | add25 | 434 | 2.89% | 61.75% |
| DISTRIBUTION | 3m | add25 | 434 | 0.46% | 51.38% |
| DISTRIBUTION | 6m | exit_to_cash | 434 | 0.00% | 0.00% |
| SHAKEOUT | 1m | add25 | 405 | 7.72% | 75.31% |
| SHAKEOUT | 3m | add25 | 405 | 23.32% | 91.85% |
| SHAKEOUT | 6m | add25 | 405 | 45.15% | 100.00% |
| TRUE_BREAKDOWN | 1m | exit_to_cash | 131 | 0.00% | 0.00% |
| TRUE_BREAKDOWN | 3m | exit_to_cash | 131 | 0.00% | 0.00% |
| TRUE_BREAKDOWN | 6m | exit_to_cash | 131 | 0.00% | 0.00% |

## Recent / Largest Events

| Ticker | Event | Label | DD | Fwd 6m | Recovery 6m | Half Recovery 6m | Lower Low | Quality | Dist Risk | Breakdown Risk |
|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|
| PLTR | 2025-11-06 | DISTRIBUTION | -15.51% | -21.80% | 0 | 1 | 1 | 0.436 | 0.636 | 0.520 |
| COP | 2025-11-06 | SHAKEOUT | -13.47% | 38.22% | 1 | 1 | 0 | 0.618 | 0.473 | 0.270 |
| HD | 2025-11-06 | TRUE_BREAKDOWN | -12.84% | -14.51% | 0 | 0 | 0 | 0.255 | 0.518 | 0.390 |
| SYK | 2025-11-06 | DISTRIBUTION | -12.12% | -19.72% | 0 | 1 | 1 | 0.164 | 0.836 | 0.640 |
| MPWR | 2025-11-04 | SHAKEOUT | -13.32% | 65.14% | 1 | 1 | 0 | 0.909 | 0.164 | 0.000 |
| ABBV | 2025-11-03 | DISTRIBUTION | -12.64% | -1.68% | 1 | 1 | 1 | 0.655 | 0.527 | 0.100 |
| GEV | 2025-11-03 | SHAKEOUT | -12.50% | 92.76% | 1 | 1 | 0 | 0.691 | 0.382 | 0.150 |
| BA | 2025-10-30 | DISTRIBUTION | -15.71% | 10.61% | 1 | 1 | 1 | 0.436 | 0.745 | 0.150 |
| AKAM | 2025-10-29 | SHAKEOUT | -14.55% | 42.27% | 1 | 1 | 0 | 0.618 | 0.636 | 0.370 |
| APP | 2025-10-28 | DISTRIBUTION | -12.76% | -28.79% | 1 | 1 | 1 | 0.727 | 0.436 | 0.200 |
| VZ | 2025-10-23 | SHAKEOUT | -13.32% | 26.66% | 1 | 1 | 0 | 0.709 | 0.473 | 0.270 |
| ON | 2025-10-22 | SHAKEOUT | -16.85% | 89.49% | 1 | 1 | 0 | 0.691 | 0.455 | 0.150 |
| RKLB | 2025-10-22 | DISTRIBUTION | -12.57% | 31.56% | 1 | 1 | 1 | 0.818 | 0.436 | 0.100 |
| MRVL | 2025-10-22 | DISTRIBUTION | -12.32% | 102.97% | 1 | 1 | 1 | 0.818 | 0.436 | 0.100 |
| NEM | 2025-10-21 | DISTRIBUTION | -12.16% | 29.30% | 1 | 1 | 1 | 0.818 | 0.436 | 0.100 |

## Next Gate

Use these event labels to train/validate a hold/add/trim/exit policy,
then run a true portfolio-level challenger replay before production activation.
