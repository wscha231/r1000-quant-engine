# Shakeout vs Distribution/Breakdown Study

Report-only event study. No production behavior is changed.

- events: 1279
- production_activation_allowed: `False`

## Label Counts

- `DISTRIBUTION`: 404
- `SHAKEOUT`: 413
- `TRUE_BREAKDOWN`: 113
- `AMBIGUOUS`: 349

## Label Medians

| Label | N | Median DD | Median 6m Return | Recovery 6m | Half Recovery 6m | Lower Low After Half | Shakeout Quality | Distribution Risk | Breakdown Risk |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| AMBIGUOUS | 349 | -12.91% | 10.16% | 67.62% | 80.52% | 2.87% | 0.600 | 0.345 | 0.150 |
| DISTRIBUTION | 404 | -12.82% | -0.72% | 59.41% | 89.11% | 86.63% | 0.545 | 0.545 | 0.200 |
| SHAKEOUT | 413 | -13.03% | 35.54% | 100.00% | 100.00% | 9.44% | 0.800 | 0.273 | 0.000 |
| TRUE_BREAKDOWN | 113 | -13.04% | -17.63% | 2.65% | 7.08% | 0.00% | 0.436 | 0.318 | 0.370 |

## Best Event-Level Actions By Label/Horizon

| Label | Horizon | Best Action | N | Median Return | Hit Rate |
|---|---|---|---:|---:|---:|
| AMBIGUOUS | 1m | add25 | 349 | 0.08% | 50.14% |
| AMBIGUOUS | 3m | add25 | 349 | 7.02% | 66.48% |
| AMBIGUOUS | 6m | add25 | 349 | 12.70% | 86.25% |
| DISTRIBUTION | 1m | add25 | 404 | 3.22% | 63.12% |
| DISTRIBUTION | 3m | add25 | 404 | 1.06% | 52.97% |
| DISTRIBUTION | 6m | exit_to_cash | 404 | 0.00% | 0.00% |
| SHAKEOUT | 1m | add25 | 413 | 7.09% | 73.85% |
| SHAKEOUT | 3m | add25 | 413 | 22.56% | 92.49% |
| SHAKEOUT | 6m | add25 | 413 | 44.42% | 100.00% |
| TRUE_BREAKDOWN | 1m | exit_to_cash | 113 | 0.00% | 0.00% |
| TRUE_BREAKDOWN | 3m | exit_to_cash | 113 | 0.00% | 0.00% |
| TRUE_BREAKDOWN | 6m | exit_to_cash | 113 | 0.00% | 0.00% |

## Recent / Largest Events

| Ticker | Event | Label | DD | Fwd 6m | Recovery 6m | Half Recovery 6m | Lower Low | Quality | Dist Risk | Breakdown Risk |
|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|
| VRT | 2025-11-12 | SHAKEOUT | -13.00% | 114.09% | 1 | 1 | 1 | 0.818 | 0.364 | 0.000 |
| PLTR | 2025-11-06 | DISTRIBUTION | -15.51% | -21.80% | 0 | 1 | 1 | 0.436 | 0.636 | 0.520 |
| COP | 2025-11-06 | SHAKEOUT | -13.47% | 38.22% | 1 | 1 | 0 | 0.618 | 0.473 | 0.270 |
| HD | 2025-11-06 | TRUE_BREAKDOWN | -12.84% | -14.51% | 0 | 0 | 0 | 0.255 | 0.518 | 0.390 |
| SYK | 2025-11-06 | DISTRIBUTION | -12.12% | -19.72% | 0 | 1 | 1 | 0.164 | 0.836 | 0.640 |
| ABBV | 2025-11-03 | DISTRIBUTION | -12.64% | -1.68% | 1 | 1 | 1 | 0.655 | 0.527 | 0.100 |
| GEV | 2025-11-03 | SHAKEOUT | -12.50% | 92.76% | 1 | 1 | 0 | 0.691 | 0.382 | 0.150 |
| LIN | 2025-10-31 | SHAKEOUT | -13.50% | 20.44% | 1 | 1 | 0 | 0.618 | 0.564 | 0.270 |
| EME | 2025-10-30 | SHAKEOUT | -16.60% | 40.63% | 1 | 1 | 0 | 0.909 | 0.164 | 0.000 |
| BA | 2025-10-30 | DISTRIBUTION | -15.71% | 10.61% | 1 | 1 | 1 | 0.436 | 0.745 | 0.150 |
| AKAM | 2025-10-29 | SHAKEOUT | -14.55% | 42.27% | 1 | 1 | 0 | 0.618 | 0.636 | 0.370 |
| APP | 2025-10-28 | DISTRIBUTION | -12.76% | -28.79% | 1 | 1 | 1 | 0.727 | 0.436 | 0.200 |
| VZ | 2025-10-23 | SHAKEOUT | -13.32% | 26.66% | 1 | 1 | 0 | 0.709 | 0.473 | 0.270 |
| ON | 2025-10-22 | SHAKEOUT | -16.85% | 89.49% | 1 | 1 | 0 | 0.691 | 0.455 | 0.150 |
| MRVL | 2025-10-22 | DISTRIBUTION | -12.32% | 102.97% | 1 | 1 | 1 | 0.818 | 0.436 | 0.100 |

## Next Gate

Use these event labels to train/validate a hold/add/trim/exit policy,
then run a true portfolio-level challenger replay before production activation.
