# Shakeout vs Distribution/Breakdown Study

Report-only event study. No production behavior is changed.

- events: 1316
- production_activation_allowed: `False`

## Label Counts

- `DISTRIBUTION`: 432
- `TRUE_BREAKDOWN`: 129
- `AMBIGUOUS`: 339
- `SHAKEOUT`: 416

## Label Medians

| Label | N | Median DD | Median 6m Return | Recovery 6m | Half Recovery 6m | Lower Low After Half | Shakeout Quality | Distribution Risk | Breakdown Risk |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| AMBIGUOUS | 339 | -12.89% | 10.02% | 68.14% | 80.24% | 2.06% | 0.618 | 0.327 | 0.150 |
| DISTRIBUTION | 432 | -12.86% | -1.38% | 58.33% | 90.05% | 87.73% | 0.545 | 0.545 | 0.200 |
| SHAKEOUT | 416 | -13.08% | 35.19% | 100.00% | 100.00% | 9.86% | 0.800 | 0.273 | 0.000 |
| TRUE_BREAKDOWN | 129 | -13.16% | -17.92% | 3.88% | 6.98% | 0.00% | 0.436 | 0.318 | 0.370 |

## Best Event-Level Actions By Label/Horizon

| Label | Horizon | Best Action | N | Median Return | Hit Rate |
|---|---|---|---:|---:|---:|
| AMBIGUOUS | 1m | add25 | 339 | 0.42% | 51.03% |
| AMBIGUOUS | 3m | add25 | 339 | 7.33% | 67.26% |
| AMBIGUOUS | 6m | add25 | 339 | 12.52% | 84.07% |
| DISTRIBUTION | 1m | add25 | 432 | 2.85% | 62.04% |
| DISTRIBUTION | 3m | add25 | 432 | 0.51% | 51.39% |
| DISTRIBUTION | 6m | exit_to_cash | 432 | 0.00% | 0.00% |
| SHAKEOUT | 1m | add25 | 416 | 7.66% | 74.52% |
| SHAKEOUT | 3m | add25 | 416 | 22.76% | 91.11% |
| SHAKEOUT | 6m | add25 | 416 | 43.99% | 100.00% |
| TRUE_BREAKDOWN | 1m | exit_to_cash | 129 | 0.00% | 0.00% |
| TRUE_BREAKDOWN | 3m | exit_to_cash | 129 | 0.00% | 0.00% |
| TRUE_BREAKDOWN | 6m | exit_to_cash | 129 | 0.00% | 0.00% |

## Recent / Largest Events

| Ticker | Event | Label | DD | Fwd 6m | Recovery 6m | Half Recovery 6m | Lower Low | Quality | Dist Risk | Breakdown Risk |
|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|
| PLTR | 2025-11-06 | DISTRIBUTION | -15.51% | -21.80% | 0 | 1 | 1 | 0.436 | 0.636 | 0.520 |
| HD | 2025-11-06 | TRUE_BREAKDOWN | -12.84% | -14.51% | 0 | 0 | 0 | 0.255 | 0.518 | 0.390 |
| MPWR | 2025-11-04 | SHAKEOUT | -13.32% | 65.14% | 1 | 1 | 0 | 0.909 | 0.164 | 0.000 |
| ABBV | 2025-11-03 | DISTRIBUTION | -12.64% | -1.68% | 1 | 1 | 1 | 0.655 | 0.527 | 0.100 |
| GEV | 2025-11-03 | SHAKEOUT | -12.50% | 92.76% | 1 | 1 | 0 | 0.691 | 0.382 | 0.150 |
| LIN | 2025-10-31 | SHAKEOUT | -13.50% | 20.44% | 1 | 1 | 0 | 0.618 | 0.564 | 0.270 |
| BA | 2025-10-30 | DISTRIBUTION | -15.71% | 10.61% | 1 | 1 | 1 | 0.436 | 0.745 | 0.150 |
| AKAM | 2025-10-29 | SHAKEOUT | -14.55% | 42.27% | 1 | 1 | 0 | 0.618 | 0.636 | 0.370 |
| VZ | 2025-10-23 | SHAKEOUT | -13.32% | 26.66% | 1 | 1 | 0 | 0.709 | 0.473 | 0.270 |
| ON | 2025-10-22 | SHAKEOUT | -16.85% | 89.49% | 1 | 1 | 0 | 0.691 | 0.455 | 0.150 |
| MRVL | 2025-10-22 | DISTRIBUTION | -12.32% | 102.97% | 1 | 1 | 1 | 0.818 | 0.436 | 0.100 |
| NEM | 2025-10-21 | DISTRIBUTION | -12.16% | 29.30% | 1 | 1 | 1 | 0.818 | 0.436 | 0.100 |
| HPE | 2025-10-16 | SHAKEOUT | -14.29% | 25.15% | 1 | 1 | 1 | 0.818 | 0.364 | 0.000 |
| ANET | 2025-10-14 | DISTRIBUTION | -12.29% | 16.01% | 1 | 1 | 1 | 0.727 | 0.436 | 0.100 |
| PG | 2025-10-13 | DISTRIBUTION | -12.59% | -1.41% | 1 | 1 | 1 | 0.345 | 0.836 | 0.220 |

## Next Gate

Use these event labels to train/validate a hold/add/trim/exit policy,
then run a true portfolio-level challenger replay before production activation.
