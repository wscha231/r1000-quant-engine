# Shakeout vs Distribution/Breakdown Study

Report-only event study. No production behavior is changed.

- events: 1351
- production_activation_allowed: `False`

## Label Counts

- `AMBIGUOUS`: 328
- `DISTRIBUTION`: 462
- `SHAKEOUT`: 430
- `TRUE_BREAKDOWN`: 131

## Label Medians

| Label | N | Median DD | Median 6m Return | Recovery 6m | Half Recovery 6m | Lower Low After Half | Shakeout Quality | Distribution Risk | Breakdown Risk |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| AMBIGUOUS | 328 | -12.90% | 10.39% | 70.12% | 82.01% | 2.13% | 0.618 | 0.327 | 0.120 |
| DISTRIBUTION | 462 | -12.88% | -1.30% | 59.96% | 91.13% | 88.96% | 0.545 | 0.545 | 0.200 |
| SHAKEOUT | 430 | -13.10% | 36.03% | 100.00% | 100.00% | 10.00% | 0.800 | 0.273 | 0.000 |
| TRUE_BREAKDOWN | 131 | -13.15% | -17.92% | 3.82% | 7.63% | 0.00% | 0.436 | 0.318 | 0.370 |

## Best Event-Level Actions By Label/Horizon

| Label | Horizon | Best Action | N | Median Return | Hit Rate |
|---|---|---|---:|---:|---:|
| AMBIGUOUS | 1m | add25 | 328 | 0.95% | 51.83% |
| AMBIGUOUS | 3m | add25 | 328 | 7.99% | 69.51% |
| AMBIGUOUS | 6m | add25 | 328 | 12.99% | 85.06% |
| DISTRIBUTION | 1m | add25 | 462 | 2.97% | 61.90% |
| DISTRIBUTION | 3m | add25 | 462 | 0.30% | 50.87% |
| DISTRIBUTION | 6m | exit_to_cash | 462 | 0.00% | 0.00% |
| SHAKEOUT | 1m | add25 | 430 | 7.93% | 74.19% |
| SHAKEOUT | 3m | add25 | 430 | 23.00% | 90.70% |
| SHAKEOUT | 6m | add25 | 430 | 45.04% | 100.00% |
| TRUE_BREAKDOWN | 1m | exit_to_cash | 131 | 0.00% | 0.00% |
| TRUE_BREAKDOWN | 3m | exit_to_cash | 131 | 0.00% | 0.00% |
| TRUE_BREAKDOWN | 6m | exit_to_cash | 131 | 0.00% | 0.00% |

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
| CEG | 2025-10-22 | DISTRIBUTION | -13.34% | -10.21% | 1 | 1 | 1 | 0.727 | 0.436 | 0.200 |
| RKLB | 2025-10-22 | DISTRIBUTION | -12.57% | 31.56% | 1 | 1 | 1 | 0.818 | 0.436 | 0.100 |
| MRVL | 2025-10-22 | DISTRIBUTION | -12.32% | 102.97% | 1 | 1 | 1 | 0.818 | 0.436 | 0.100 |
| NEM | 2025-10-21 | DISTRIBUTION | -12.16% | 29.30% | 1 | 1 | 1 | 0.818 | 0.436 | 0.100 |
| HPE | 2025-10-16 | SHAKEOUT | -14.29% | 25.15% | 1 | 1 | 1 | 0.818 | 0.364 | 0.000 |
| ANET | 2025-10-14 | DISTRIBUTION | -12.29% | 16.01% | 1 | 1 | 1 | 0.727 | 0.436 | 0.100 |

## Next Gate

Use these event labels to train/validate a hold/add/trim/exit policy,
then run a true portfolio-level challenger replay before production activation.
