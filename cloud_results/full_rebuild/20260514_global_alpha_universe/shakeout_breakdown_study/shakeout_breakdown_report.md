# Shakeout vs Distribution/Breakdown Study

Report-only event study. No production behavior is changed.

- events: 1340
- production_activation_allowed: `False`

## Label Counts

- `DISTRIBUTION`: 457
- `SHAKEOUT`: 417
- `AMBIGUOUS`: 336
- `TRUE_BREAKDOWN`: 130

## Label Medians

| Label | N | Median DD | Median 6m Return | Recovery 6m | Half Recovery 6m | Lower Low After Half | Shakeout Quality | Distribution Risk | Breakdown Risk |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| AMBIGUOUS | 336 | -12.93% | 9.84% | 66.96% | 78.27% | 3.57% | 0.618 | 0.327 | 0.150 |
| DISTRIBUTION | 457 | -12.91% | -0.36% | 60.61% | 91.47% | 89.72% | 0.545 | 0.545 | 0.200 |
| SHAKEOUT | 417 | -13.04% | 36.40% | 100.00% | 100.00% | 9.59% | 0.800 | 0.273 | 0.000 |
| TRUE_BREAKDOWN | 130 | -13.15% | -17.51% | 4.62% | 9.23% | 0.00% | 0.436 | 0.318 | 0.370 |

## Best Event-Level Actions By Label/Horizon

| Label | Horizon | Best Action | N | Median Return | Hit Rate |
|---|---|---|---:|---:|---:|
| AMBIGUOUS | 1m | add25 | 336 | 0.58% | 51.49% |
| AMBIGUOUS | 3m | add25 | 336 | 7.06% | 67.26% |
| AMBIGUOUS | 6m | add25 | 336 | 12.30% | 83.93% |
| DISTRIBUTION | 1m | add25 | 457 | 2.85% | 62.80% |
| DISTRIBUTION | 3m | add25 | 457 | 1.01% | 53.39% |
| DISTRIBUTION | 6m | exit_to_cash | 457 | 0.00% | 0.00% |
| SHAKEOUT | 1m | add25 | 417 | 7.30% | 72.66% |
| SHAKEOUT | 3m | add25 | 417 | 24.19% | 91.85% |
| SHAKEOUT | 6m | add25 | 417 | 45.49% | 100.00% |
| TRUE_BREAKDOWN | 1m | exit_to_cash | 130 | 0.00% | 0.00% |
| TRUE_BREAKDOWN | 3m | exit_to_cash | 130 | 0.00% | 0.00% |
| TRUE_BREAKDOWN | 6m | exit_to_cash | 130 | 0.00% | 0.00% |

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
| AVT | 2025-10-29 | SHAKEOUT | -13.04% | 67.69% | 1 | 1 | 0 | 0.618 | 0.473 | 0.270 |
| APP | 2025-10-28 | DISTRIBUTION | -12.76% | -28.79% | 1 | 1 | 1 | 0.727 | 0.436 | 0.200 |
| VZ | 2025-10-23 | SHAKEOUT | -13.32% | 26.66% | 1 | 1 | 0 | 0.709 | 0.473 | 0.270 |
| ON | 2025-10-22 | SHAKEOUT | -16.85% | 89.49% | 1 | 1 | 0 | 0.691 | 0.455 | 0.150 |
| MRVL | 2025-10-22 | DISTRIBUTION | -12.32% | 102.97% | 1 | 1 | 1 | 0.818 | 0.436 | 0.100 |
| NEM | 2025-10-21 | DISTRIBUTION | -12.16% | 29.30% | 1 | 1 | 1 | 0.818 | 0.436 | 0.100 |

## Next Gate

Use these event labels to train/validate a hold/add/trim/exit policy,
then run a true portfolio-level challenger replay before production activation.
