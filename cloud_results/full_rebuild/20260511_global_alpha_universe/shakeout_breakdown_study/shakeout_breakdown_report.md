# Shakeout vs Distribution/Breakdown Study

Report-only event study. No production behavior is changed.

- events: 1327
- production_activation_allowed: `False`

## Label Counts

- `DISTRIBUTION`: 433
- `TRUE_BREAKDOWN`: 124
- `AMBIGUOUS`: 342
- `SHAKEOUT`: 428

## Label Medians

| Label | N | Median DD | Median 6m Return | Recovery 6m | Half Recovery 6m | Lower Low After Half | Shakeout Quality | Distribution Risk | Breakdown Risk |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| AMBIGUOUS | 342 | -12.90% | 10.31% | 69.59% | 81.87% | 1.75% | 0.618 | 0.327 | 0.130 |
| DISTRIBUTION | 433 | -12.84% | -1.19% | 59.58% | 90.53% | 88.22% | 0.545 | 0.545 | 0.200 |
| SHAKEOUT | 428 | -13.04% | 35.90% | 100.00% | 100.00% | 10.05% | 0.800 | 0.273 | 0.000 |
| TRUE_BREAKDOWN | 124 | -13.19% | -17.90% | 4.03% | 8.06% | 0.00% | 0.436 | 0.318 | 0.370 |

## Best Event-Level Actions By Label/Horizon

| Label | Horizon | Best Action | N | Median Return | Hit Rate |
|---|---|---|---:|---:|---:|
| AMBIGUOUS | 1m | add25 | 342 | 0.53% | 51.75% |
| AMBIGUOUS | 3m | add25 | 342 | 8.19% | 69.30% |
| AMBIGUOUS | 6m | add25 | 342 | 12.88% | 85.67% |
| DISTRIBUTION | 1m | add25 | 433 | 2.86% | 63.05% |
| DISTRIBUTION | 3m | add25 | 433 | 0.97% | 52.42% |
| DISTRIBUTION | 6m | exit_to_cash | 433 | 0.00% | 0.00% |
| SHAKEOUT | 1m | add25 | 428 | 7.71% | 74.53% |
| SHAKEOUT | 3m | add25 | 428 | 23.32% | 91.12% |
| SHAKEOUT | 6m | add25 | 428 | 44.88% | 100.00% |
| TRUE_BREAKDOWN | 1m | exit_to_cash | 124 | 0.00% | 0.00% |
| TRUE_BREAKDOWN | 3m | exit_to_cash | 124 | 0.00% | 0.00% |
| TRUE_BREAKDOWN | 6m | exit_to_cash | 124 | 0.00% | 0.00% |

## Recent / Largest Events

| Ticker | Event | Label | DD | Fwd 6m | Recovery 6m | Half Recovery 6m | Lower Low | Quality | Dist Risk | Breakdown Risk |
|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|
| MPWR | 2025-11-04 | SHAKEOUT | -13.32% | 65.14% | 1 | 1 | 0 | 0.909 | 0.164 | 0.000 |
| ABBV | 2025-11-03 | DISTRIBUTION | -12.64% | -1.68% | 1 | 1 | 1 | 0.655 | 0.527 | 0.100 |
| GEV | 2025-11-03 | SHAKEOUT | -12.50% | 92.76% | 1 | 1 | 0 | 0.691 | 0.382 | 0.150 |
| LIN | 2025-10-31 | SHAKEOUT | -13.50% | 20.44% | 1 | 1 | 0 | 0.618 | 0.564 | 0.270 |
| BA | 2025-10-30 | DISTRIBUTION | -15.71% | 10.61% | 1 | 1 | 1 | 0.436 | 0.745 | 0.150 |
| AKAM | 2025-10-29 | SHAKEOUT | -14.55% | 42.27% | 1 | 1 | 0 | 0.618 | 0.636 | 0.370 |
| APP | 2025-10-28 | DISTRIBUTION | -12.76% | -28.79% | 1 | 1 | 1 | 0.727 | 0.436 | 0.200 |
| VZ | 2025-10-23 | SHAKEOUT | -13.32% | 26.66% | 1 | 1 | 0 | 0.709 | 0.473 | 0.270 |
| ON | 2025-10-22 | SHAKEOUT | -16.85% | 89.49% | 1 | 1 | 0 | 0.691 | 0.455 | 0.150 |
| MRVL | 2025-10-22 | DISTRIBUTION | -12.32% | 102.97% | 1 | 1 | 1 | 0.818 | 0.436 | 0.100 |
| NEM | 2025-10-21 | DISTRIBUTION | -12.16% | 29.30% | 1 | 1 | 1 | 0.818 | 0.436 | 0.100 |
| HPE | 2025-10-16 | SHAKEOUT | -14.29% | 25.15% | 1 | 1 | 1 | 0.818 | 0.364 | 0.000 |
| ANET | 2025-10-14 | DISTRIBUTION | -12.29% | 16.01% | 1 | 1 | 1 | 0.727 | 0.436 | 0.100 |
| PG | 2025-10-13 | DISTRIBUTION | -12.59% | -1.41% | 1 | 1 | 1 | 0.345 | 0.836 | 0.220 |
| KLAC | 2025-10-10 | SHAKEOUT | -13.77% | 83.29% | 1 | 1 | 0 | 0.909 | 0.236 | 0.000 |

## Next Gate

Use these event labels to train/validate a hold/add/trim/exit policy,
then run a true portfolio-level challenger replay before production activation.
