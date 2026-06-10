# Shakeout vs Distribution/Breakdown Study

Report-only event study. No production behavior is changed.

- events: 1321
- production_activation_allowed: `False`

## Label Counts

- `DISTRIBUTION`: 442
- `TRUE_BREAKDOWN`: 131
- `AMBIGUOUS`: 345
- `SHAKEOUT`: 403

## Label Medians

| Label | N | Median DD | Median 6m Return | Recovery 6m | Half Recovery 6m | Lower Low After Half | Shakeout Quality | Distribution Risk | Breakdown Risk |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| AMBIGUOUS | 345 | -12.86% | 10.02% | 69.28% | 80.87% | 2.03% | 0.600 | 0.345 | 0.150 |
| DISTRIBUTION | 442 | -12.83% | -1.18% | 58.82% | 89.82% | 86.88% | 0.545 | 0.545 | 0.200 |
| SHAKEOUT | 403 | -13.11% | 35.68% | 100.00% | 100.00% | 9.93% | 0.800 | 0.273 | 0.000 |
| TRUE_BREAKDOWN | 131 | -13.15% | -17.11% | 3.05% | 6.87% | 0.00% | 0.436 | 0.318 | 0.370 |

## Best Event-Level Actions By Label/Horizon

| Label | Horizon | Best Action | N | Median Return | Hit Rate |
|---|---|---|---:|---:|---:|
| AMBIGUOUS | 1m | add25 | 345 | 0.14% | 50.14% |
| AMBIGUOUS | 3m | add25 | 345 | 7.40% | 68.41% |
| AMBIGUOUS | 6m | add25 | 345 | 12.52% | 84.93% |
| DISTRIBUTION | 1m | add25 | 442 | 2.84% | 61.99% |
| DISTRIBUTION | 3m | add25 | 442 | 0.99% | 53.62% |
| DISTRIBUTION | 6m | exit_to_cash | 442 | 0.00% | 0.00% |
| SHAKEOUT | 1m | add25 | 403 | 7.34% | 75.68% |
| SHAKEOUT | 3m | add25 | 403 | 23.32% | 92.31% |
| SHAKEOUT | 6m | add25 | 403 | 44.60% | 100.00% |
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
| MRVL | 2025-10-22 | DISTRIBUTION | -12.32% | 102.97% | 1 | 1 | 1 | 0.818 | 0.436 | 0.100 |
| NEM | 2025-10-21 | DISTRIBUTION | -12.16% | 29.30% | 1 | 1 | 1 | 0.818 | 0.436 | 0.100 |
| HPE | 2025-10-16 | SHAKEOUT | -14.29% | 25.15% | 1 | 1 | 1 | 0.818 | 0.364 | 0.000 |

## Next Gate

Use these event labels to train/validate a hold/add/trim/exit policy,
then run a true portfolio-level challenger replay before production activation.
