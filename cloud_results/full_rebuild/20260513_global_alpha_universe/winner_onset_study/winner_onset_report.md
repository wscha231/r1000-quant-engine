# Winner Onset Study

Report-only historical study. No production behavior is changed.

- events: 29
- production_activation_allowed: False

## Winner Tiers

- `major_2_5x`: 24
- `super_5x`: 4
- `monster_10x`: 1

## Median Onset Pattern

- readiness score: 0.664
- 1m momentum: 7.9%
- 3m momentum: 11.8%
- 6m momentum: 4.3%
- RS vs SPY 3m: 9.2%
- volume surge: 1.06x
- distance to 52w high: -20.7%
- first 3m max drawdown: -15.9%

## Top Events

| ticker | onset | peak | tier | 12m peak return | multiple | fwd 6m | readiness |
|---|---:|---:|---|---:|---:|---:|---:|
| TSLA | 2019-09-11 | 2020-08-31 | monster_10x | 908.3% | 10.08x | 126.9% | 0.664 |
| STX | 2025-05-05 | 2026-05-06 | super_5x | 751.2% | 8.51x | 186.2% | 0.573 |
| LITE | 2025-02-11 | 2026-02-12 | super_5x | 633.0% | 7.33x | 51.0% | 0.591 |
| RKLB | 2024-06-18 | 2025-06-23 | super_5x | 567.6% | 6.68x | 437.1% | 0.755 |
| PLTR | 2024-08-09 | 2025-08-12 | super_5x | 523.0% | 6.23x | 275.3% | 1.000 |
| APP | 2024-10-10 | 2025-09-30 | major_2_5x | 396.1% | 4.96x | 63.0% | 1.000 |
| APP | 2023-04-17 | 2024-04-11 | major_2_5x | 378.8% | 4.79x | 138.0% | 0.591 |
| MU | 2025-03-14 | 2026-03-17 | major_2_5x | 359.6% | 4.60x | 56.9% | 0.618 |
| FCX | 2020-06-05 | 2021-05-11 | major_2_5x | 313.4% | 4.13x | 124.6% | 0.709 |
| VRT | 2022-12-07 | 2023-12-08 | major_2_5x | 245.3% | 3.45x | 55.1% | 0.727 |
| GLW | 2025-03-19 | 2026-02-25 | major_2_5x | 233.4% | 3.33x | 64.9% | 0.682 |
| LRCX | 2025-03-12 | 2026-02-25 | major_2_5x | 227.7% | 3.28x | 51.3% | 0.591 |
| GEV | 2025-04-09 | 2026-04-10 | major_2_5x | 204.2% | 3.04x | 94.3% | 0.591 |
| PLTR | 2023-02-08 | 2024-02-08 | major_2_5x | 198.2% | 2.98x | 87.5% | 0.709 |
| NVDA | 2022-11-30 | 2023-11-20 | major_2_5x | 198.0% | 2.98x | 132.4% | 0.709 |

## Monster Winner Archive

| ticker | onset | peak | tier | 12m peak return | multiple | readiness |
|---|---:|---:|---|---:|---:|---:|
| TSLA | 2019-09-11 | 2020-08-31 | monster_10x | 908.3% | 10.08x | 0.664 |
| STX | 2025-05-05 | 2026-05-06 | super_5x | 751.2% | 8.51x | 0.573 |
| LITE | 2025-02-11 | 2026-02-12 | super_5x | 633.0% | 7.33x | 0.591 |
| RKLB | 2024-06-18 | 2025-06-23 | super_5x | 567.6% | 6.68x | 0.755 |
| PLTR | 2024-08-09 | 2025-08-12 | super_5x | 523.0% | 6.23x | 1.000 |

## Files

- `outputs/winner_onset_study/events.csv`
- `outputs/winner_onset_study/phase_snapshots.csv`
- `outputs/winner_onset_study/hold_diagnostics.csv`
- `outputs/winner_onset_study/pattern_summary.json`
- `outputs/winner_onset_study/system_policy_candidates.yaml`

## Next Gate

Use this report to propose counterfactual rules, then test those rules
through a true historical challenger replay before any production wiring.
