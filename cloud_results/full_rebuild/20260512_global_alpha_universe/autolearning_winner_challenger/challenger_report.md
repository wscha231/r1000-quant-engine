# AutoLearning Winner Challenger

Research-only harness connecting AutoLearning v2 with winner lifecycle, winner onset, and shakeout/breakdown studies.

## Verdict

- `READY_FOR_PORTFOLIO_CHALLENGER_REPLAY`
- production_activation_allowed: `False`

## Baseline

- Main CAGR / Sharpe / MaxDD: 29.19% / 1.7248976396719429 / -17.46%
- Main avg/latest cash: 20.93% / 28.89%
- Concentrated CAGR / Sharpe / MaxDD: 48.94% / 1.7406704160388327 / -16.67%

## Connected Signals

- AutoLearning hypotheses: 6
- Missed winners: 30 top=['SNDK', 'STX', 'LITE', 'FLEX', 'CIEN', 'RKLB', 'HIMX', 'BE']
- Stale winners: 1 top=['PLTR']
- Leadership rotations: 16 top=['PLTR->SNDK', 'AKAM->SNDK', 'LRCX->SNDK', 'ON->SNDK', 'GLW->SNDK', 'MLI->RKLB', 'NXPI->STM', 'TKR->RKLB']
- Onset events: 26
- Shakeout/breakdown events: 1321 labels={'AMBIGUOUS': 345, 'DISTRIBUTION': 442, 'SHAKEOUT': 403, 'TRUE_BREAKDOWN': 131}
- Main cash-drag replay: available best=cash0.00_cap0.18
- Main v2 historical replay: completed
- Concentrated policy replay: completed
- Alpha Sprint historical sidecar: inactive_no_bull_months_or_candidates
- Position-aware risk replay: completed
- Monster lifecycle replay: completed policy=concentrated

## Event-Level Backtest

| Strategy | N | Median | Avg | Hit Rate | Worst | Best |
|---|---:|---:|---:|---:|---:|---:|
| hold_3m_return | 26 | 33.46% | 35.30% | 84.62% | -6.39% | 117.95% |
| hold_6m_return | 26 | 76.65% | 90.34% | 100.00% | 50.47% | 275.27% |
| hold_12m_return | 26 | 186.87% | 263.11% | 100.00% | 116.97% | 751.20% |
| hold_18m_return | 17 | 238.82% | 347.24% | 100.00% | 90.11% | 1303.74% |
| trail20_after_50pct_return | 25 | 120.13% | 179.38% | 100.00% | 32.96% | 601.56% |
| ma50_5d_after_50pct_return | 23 | 121.91% | 142.75% | 100.00% | 27.52% | 537.71% |
| ma200_after_50pct_return | 18 | 128.76% | 336.62% | 100.00% | 15.27% | 1814.23% |

## Shakeout/Breakdown Action Backtest

| Label | Horizon | Action | N | Median | Avg | Hit Rate | Worst |
|---|---|---|---:|---:|---:|---:|---:|
| AMBIGUOUS | 6m | add25 | 345 | 12.52% | 11.24% | 84.93% | -12.40% |
| AMBIGUOUS | 6m | exit_to_cash | 345 | 0.00% | 0.00% | 0.00% | 0.00% |
| AMBIGUOUS | 6m | hold | 345 | 10.02% | 8.99% | 84.93% | -9.92% |
| AMBIGUOUS | 6m | label_oracle | 345 | 5.01% | 4.50% | 84.93% | -4.96% |
| AMBIGUOUS | 6m | trim50 | 345 | 5.01% | 4.50% | 84.93% | -4.96% |
| DISTRIBUTION | 6m | add25 | 442 | -1.48% | 0.62% | 47.06% | -73.44% |
| DISTRIBUTION | 6m | exit_to_cash | 442 | 0.00% | 0.00% | 0.00% | 0.00% |
| DISTRIBUTION | 6m | hold | 442 | -1.18% | 0.50% | 47.06% | -58.75% |
| DISTRIBUTION | 6m | label_oracle | 442 | 0.00% | 0.00% | 0.00% | 0.00% |
| DISTRIBUTION | 6m | trim50 | 442 | -0.59% | 0.25% | 47.06% | -29.37% |
| SHAKEOUT | 6m | add25 | 403 | 44.60% | 59.13% | 100.00% | 25.11% |
| SHAKEOUT | 6m | exit_to_cash | 403 | 0.00% | 0.00% | 0.00% | 0.00% |
| SHAKEOUT | 6m | hold | 403 | 35.68% | 47.30% | 100.00% | 20.09% |
| SHAKEOUT | 6m | label_oracle | 403 | 44.60% | 59.13% | 100.00% | 25.11% |
| SHAKEOUT | 6m | trim50 | 403 | 17.84% | 23.65% | 100.00% | 10.05% |
| TRUE_BREAKDOWN | 6m | add25 | 131 | -21.39% | -22.72% | 9.92% | -70.38% |
| TRUE_BREAKDOWN | 6m | exit_to_cash | 131 | 0.00% | 0.00% | 0.00% | 0.00% |
| TRUE_BREAKDOWN | 6m | hold | 131 | -17.11% | -18.18% | 9.92% | -56.30% |
| TRUE_BREAKDOWN | 6m | label_oracle | 131 | 0.00% | 0.00% | 0.00% | 0.00% |
| TRUE_BREAKDOWN | 6m | trim50 | 131 | -8.56% | -9.09% | 9.92% | -28.15% |

## Portfolio Replay Readiness

- status: `ready`
- missing: []
- policy_value_replay: `CAGR_FIRST_REPLAY_REQUIRED`

Event-level evidence can prioritize rules. It is not a substitute for portfolio-level CAGR/MaxDD replay.
