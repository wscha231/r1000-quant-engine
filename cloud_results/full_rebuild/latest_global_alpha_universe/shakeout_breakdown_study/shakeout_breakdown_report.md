# Shakeout vs Distribution/Breakdown Study

Report-only event study. No production behavior is changed.

- events: 1332
- production_activation_allowed: `False`

## Label Counts

- `DISTRIBUTION`: 447
- `SHAKEOUT`: 422
- `TRUE_BREAKDOWN`: 126
- `AMBIGUOUS`: 337

## Label Medians

| Label | N | Median DD | Median 6m Return | Recovery 6m | Half Recovery 6m | Lower Low After Half | Shakeout Quality | Distribution Risk | Breakdown Risk |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| AMBIGUOUS | 337 | -12.89% | 9.83% | 66.17% | 78.34% | 3.56% | 0.600 | 0.327 | 0.150 |
| DISTRIBUTION | 447 | -12.87% | -1.09% | 58.61% | 91.28% | 89.26% | 0.545 | 0.545 | 0.200 |
| SHAKEOUT | 422 | -13.04% | 36.43% | 100.00% | 100.00% | 8.77% | 0.800 | 0.273 | 0.000 |
| TRUE_BREAKDOWN | 126 | -13.25% | -18.08% | 4.76% | 9.52% | 0.00% | 0.436 | 0.318 | 0.370 |

## Best Event-Level Actions By Label/Horizon

| Label | Horizon | Best Action | N | Median Return | Hit Rate |
|---|---|---|---:|---:|---:|
| AMBIGUOUS | 1m | add25 | 337 | 0.64% | 51.63% |
| AMBIGUOUS | 3m | add25 | 337 | 7.02% | 67.06% |
| AMBIGUOUS | 6m | add25 | 337 | 12.29% | 84.27% |
| DISTRIBUTION | 1m | add25 | 447 | 2.43% | 60.63% |
| DISTRIBUTION | 3m | add25 | 447 | 0.95% | 52.35% |
| DISTRIBUTION | 6m | exit_to_cash | 447 | 0.00% | 0.00% |
| SHAKEOUT | 1m | add25 | 422 | 7.17% | 73.46% |
| SHAKEOUT | 3m | add25 | 422 | 23.73% | 92.42% |
| SHAKEOUT | 6m | add25 | 422 | 45.54% | 100.00% |
| TRUE_BREAKDOWN | 1m | exit_to_cash | 126 | 0.00% | 0.00% |
| TRUE_BREAKDOWN | 3m | exit_to_cash | 126 | 0.00% | 0.00% |
| TRUE_BREAKDOWN | 6m | exit_to_cash | 126 | 0.00% | 0.00% |

## Recent / Largest Events

| Ticker | Event | Label | DD | Fwd 6m | Recovery 6m | Half Recovery 6m | Lower Low | Quality | Dist Risk | Breakdown Risk |
|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|
| PLTR | 2025-11-06 | DISTRIBUTION | -15.51% | -21.80% | 0 | 1 | 1 | 0.436 | 0.636 | 0.520 |
| SYK | 2025-11-06 | DISTRIBUTION | -12.12% | -19.72% | 0 | 1 | 1 | 0.164 | 0.836 | 0.640 |
| MPWR | 2025-11-04 | SHAKEOUT | -13.32% | 65.14% | 1 | 1 | 0 | 0.909 | 0.164 | 0.000 |
| ABBV | 2025-11-03 | DISTRIBUTION | -12.64% | -1.68% | 1 | 1 | 1 | 0.655 | 0.527 | 0.100 |
| GEV | 2025-11-03 | SHAKEOUT | -12.50% | 92.76% | 1 | 1 | 0 | 0.691 | 0.382 | 0.150 |
| LIN | 2025-10-31 | SHAKEOUT | -13.50% | 20.44% | 1 | 1 | 0 | 0.618 | 0.564 | 0.270 |
| EME | 2025-10-30 | SHAKEOUT | -16.60% | 40.63% | 1 | 1 | 0 | 0.909 | 0.164 | 0.000 |
| BA | 2025-10-30 | DISTRIBUTION | -15.71% | 10.61% | 1 | 1 | 1 | 0.436 | 0.745 | 0.150 |
| AKAM | 2025-10-29 | SHAKEOUT | -14.55% | 42.27% | 1 | 1 | 0 | 0.618 | 0.636 | 0.370 |
| UNH | 2025-10-29 | AMBIGUOUS | -12.49% | 5.32% | 0 | 0 | 0 | 0.364 | 0.409 | 0.390 |
| APP | 2025-10-28 | DISTRIBUTION | -12.76% | -28.79% | 1 | 1 | 1 | 0.727 | 0.436 | 0.200 |
| VZ | 2025-10-23 | SHAKEOUT | -13.32% | 26.66% | 1 | 1 | 0 | 0.709 | 0.473 | 0.270 |
| ON | 2025-10-22 | SHAKEOUT | -16.85% | 89.49% | 1 | 1 | 0 | 0.691 | 0.455 | 0.150 |
| MRVL | 2025-10-22 | DISTRIBUTION | -12.32% | 102.97% | 1 | 1 | 1 | 0.818 | 0.436 | 0.100 |
| NEM | 2025-10-21 | DISTRIBUTION | -12.16% | 29.30% | 1 | 1 | 1 | 0.818 | 0.436 | 0.100 |

## Next Gate

Use these event labels to train/validate a hold/add/trim/exit policy,
then run a true portfolio-level challenger replay before production activation.
