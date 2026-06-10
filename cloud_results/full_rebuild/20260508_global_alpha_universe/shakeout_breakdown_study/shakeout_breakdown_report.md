# Shakeout vs Distribution/Breakdown Study

Report-only event study. No production behavior is changed.

- events: 1316
- production_activation_allowed: `False`

## Label Counts

- `AMBIGUOUS`: 343
- `DISTRIBUTION`: 416
- `SHAKEOUT`: 430
- `TRUE_BREAKDOWN`: 127

## Label Medians

| Label | N | Median DD | Median 6m Return | Recovery 6m | Half Recovery 6m | Lower Low After Half | Shakeout Quality | Distribution Risk | Breakdown Risk |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| AMBIGUOUS | 343 | -12.88% | 10.23% | 68.80% | 81.34% | 3.21% | 0.618 | 0.345 | 0.130 |
| DISTRIBUTION | 416 | -12.86% | -0.81% | 58.17% | 89.66% | 87.02% | 0.545 | 0.545 | 0.200 |
| SHAKEOUT | 430 | -13.08% | 35.90% | 100.00% | 100.00% | 10.00% | 0.800 | 0.273 | 0.000 |
| TRUE_BREAKDOWN | 127 | -13.16% | -17.63% | 3.15% | 7.09% | 0.00% | 0.436 | 0.318 | 0.370 |

## Best Event-Level Actions By Label/Horizon

| Label | Horizon | Best Action | N | Median Return | Hit Rate |
|---|---|---|---:|---:|---:|
| AMBIGUOUS | 1m | add25 | 343 | 0.00% | 49.85% |
| AMBIGUOUS | 3m | add25 | 343 | 7.10% | 68.22% |
| AMBIGUOUS | 6m | add25 | 343 | 12.79% | 86.30% |
| DISTRIBUTION | 1m | add25 | 416 | 2.83% | 62.26% |
| DISTRIBUTION | 3m | add25 | 416 | 0.89% | 52.40% |
| DISTRIBUTION | 6m | exit_to_cash | 416 | 0.00% | 0.00% |
| SHAKEOUT | 1m | add25 | 430 | 7.56% | 74.42% |
| SHAKEOUT | 3m | add25 | 430 | 23.00% | 91.16% |
| SHAKEOUT | 6m | add25 | 430 | 44.88% | 100.00% |
| TRUE_BREAKDOWN | 1m | exit_to_cash | 127 | 0.00% | 0.00% |
| TRUE_BREAKDOWN | 3m | exit_to_cash | 127 | 0.00% | 0.00% |
| TRUE_BREAKDOWN | 6m | exit_to_cash | 127 | 0.00% | 0.00% |

## Recent / Largest Events

| Ticker | Event | Label | DD | Fwd 6m | Recovery 6m | Half Recovery 6m | Lower Low | Quality | Dist Risk | Breakdown Risk |
|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|
| MPWR | 2025-11-04 | SHAKEOUT | -13.32% | 65.14% | 1 | 1 | 0 | 0.909 | 0.164 | 0.000 |
| GEV | 2025-11-03 | SHAKEOUT | -12.50% | 92.76% | 1 | 1 | 0 | 0.691 | 0.382 | 0.150 |
| LIN | 2025-10-31 | SHAKEOUT | -13.50% | 20.44% | 1 | 1 | 0 | 0.618 | 0.564 | 0.270 |
| EME | 2025-10-30 | SHAKEOUT | -16.60% | 40.63% | 1 | 1 | 0 | 0.909 | 0.164 | 0.000 |
| VZ | 2025-10-23 | SHAKEOUT | -13.32% | 26.66% | 1 | 1 | 0 | 0.709 | 0.473 | 0.270 |
| ON | 2025-10-22 | SHAKEOUT | -16.85% | 89.49% | 1 | 1 | 0 | 0.691 | 0.455 | 0.150 |
| MRVL | 2025-10-22 | DISTRIBUTION | -12.32% | 102.97% | 1 | 1 | 1 | 0.818 | 0.436 | 0.100 |
| NEM | 2025-10-21 | DISTRIBUTION | -12.16% | 29.30% | 1 | 1 | 1 | 0.818 | 0.436 | 0.100 |
| HPE | 2025-10-16 | SHAKEOUT | -14.29% | 25.15% | 1 | 1 | 1 | 0.818 | 0.364 | 0.000 |
| ANET | 2025-10-14 | DISTRIBUTION | -12.29% | 16.01% | 1 | 1 | 1 | 0.727 | 0.436 | 0.100 |
| PG | 2025-10-13 | DISTRIBUTION | -12.59% | -1.41% | 1 | 1 | 1 | 0.345 | 0.836 | 0.220 |
| ENTG | 2025-10-10 | DISTRIBUTION | -16.58% | 64.64% | 1 | 1 | 1 | 0.818 | 0.436 | 0.100 |
| KLAC | 2025-10-10 | SHAKEOUT | -13.77% | 83.29% | 1 | 1 | 0 | 0.909 | 0.236 | 0.000 |
| NXPI | 2025-10-10 | DISTRIBUTION | -13.70% | 3.19% | 1 | 1 | 1 | 0.509 | 0.545 | 0.150 |
| LITE | 2025-10-10 | SHAKEOUT | -12.76% | 470.01% | 1 | 1 | 0 | 0.909 | 0.236 | 0.100 |

## Next Gate

Use these event labels to train/validate a hold/add/trim/exit policy,
then run a true portfolio-level challenger replay before production activation.
