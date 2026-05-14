# AutoLearning Winner Challenger

Research-only harness connecting AutoLearning v2 with winner lifecycle, winner onset, and shakeout/breakdown studies.

## Verdict

- `READY_FOR_PORTFOLIO_CHALLENGER_REPLAY`
- production_activation_allowed: `False`

## Baseline

- Main CAGR / Sharpe / MaxDD: 29.79% / 1.7111635028673302 / -16.65%
- Main avg/latest cash: 20.23% / 28.00%
- Concentrated CAGR / Sharpe / MaxDD: 48.62% / 1.733861454092223 / -21.05%

## Connected Signals

- AutoLearning hypotheses: 5
- Missed winners: 30 top=['SNDK', 'STX', 'LITE', 'HIMX', 'FLEX', 'CIEN', 'AMD', 'BE']
- Stale winners: 1 top=['TKR']
- Leadership rotations: 10 top=['HPE->SNDK', 'ARM->SNDK', 'MRVL->SNDK', 'ON->SNDK', 'MLI->BE', 'TKR->BE', 'GEV->BE', 'VRT->BE']
- Onset events: 30
- Shakeout/breakdown events: 1330 labels={'AMBIGUOUS': 337, 'DISTRIBUTION': 453, 'SHAKEOUT': 413, 'TRUE_BREAKDOWN': 127}
- Main cash-drag replay: available best=cash0.00_cap0.33
- Main v2 historical replay: completed
- Concentrated policy replay: completed
- Alpha Sprint historical sidecar: completed
- Position-aware risk replay: completed
- Monster lifecycle replay: completed policy=concentrated

## Event-Level Backtest

| Strategy | N | Median | Avg | Hit Rate | Worst | Best |
|---|---:|---:|---:|---:|---:|---:|
| hold_3m_return | 30 | 30.94% | 34.31% | 86.67% | -6.39% | 117.95% |
| hold_6m_return | 30 | 81.45% | 102.20% | 100.00% | 50.47% | 437.07% |
| hold_12m_return | 30 | 182.43% | 259.86% | 100.00% | 79.82% | 751.20% |
| hold_18m_return | 21 | 221.80% | 367.83% | 100.00% | 90.11% | 1336.25% |
| trail20_after_50pct_return | 29 | 119.43% | 176.98% | 100.00% | 32.96% | 601.56% |
| ma50_5d_after_50pct_return | 27 | 121.21% | 140.65% | 100.00% | 27.52% | 537.71% |
| ma200_after_50pct_return | 21 | 117.60% | 302.83% | 100.00% | 15.27% | 1814.23% |

## Shakeout/Breakdown Action Backtest

| Label | Horizon | Action | N | Median | Avg | Hit Rate | Worst |
|---|---|---|---:|---:|---:|---:|---:|
| AMBIGUOUS | 6m | add25 | 337 | 12.70% | 11.06% | 84.27% | -12.40% |
| AMBIGUOUS | 6m | exit_to_cash | 337 | 0.00% | 0.00% | 0.00% | 0.00% |
| AMBIGUOUS | 6m | hold | 337 | 10.16% | 8.84% | 84.27% | -9.92% |
| AMBIGUOUS | 6m | label_oracle | 337 | 5.08% | 4.42% | 84.27% | -4.96% |
| AMBIGUOUS | 6m | trim50 | 337 | 5.08% | 4.42% | 84.27% | -4.96% |
| DISTRIBUTION | 6m | add25 | 453 | -0.36% | 1.88% | 49.45% | -73.44% |
| DISTRIBUTION | 6m | exit_to_cash | 453 | 0.00% | 0.00% | 0.00% | 0.00% |
| DISTRIBUTION | 6m | hold | 453 | -0.28% | 1.51% | 49.45% | -58.75% |
| DISTRIBUTION | 6m | label_oracle | 453 | 0.00% | 0.00% | 0.00% | 0.00% |
| DISTRIBUTION | 6m | trim50 | 453 | -0.14% | 0.75% | 49.45% | -29.37% |
| SHAKEOUT | 6m | add25 | 413 | 45.59% | 61.56% | 100.00% | 25.11% |
| SHAKEOUT | 6m | exit_to_cash | 413 | 0.00% | 0.00% | 0.00% | 0.00% |
| SHAKEOUT | 6m | hold | 413 | 36.48% | 49.25% | 100.00% | 20.09% |
| SHAKEOUT | 6m | label_oracle | 413 | 45.59% | 61.56% | 100.00% | 25.11% |
| SHAKEOUT | 6m | trim50 | 413 | 18.24% | 24.63% | 100.00% | 10.05% |
| TRUE_BREAKDOWN | 6m | add25 | 127 | -21.47% | -21.83% | 14.17% | -70.38% |
| TRUE_BREAKDOWN | 6m | exit_to_cash | 127 | 0.00% | 0.00% | 0.00% | 0.00% |
| TRUE_BREAKDOWN | 6m | hold | 127 | -17.18% | -17.46% | 14.17% | -56.30% |
| TRUE_BREAKDOWN | 6m | label_oracle | 127 | 0.00% | 0.00% | 0.00% | 0.00% |
| TRUE_BREAKDOWN | 6m | trim50 | 127 | -8.59% | -8.73% | 14.17% | -28.15% |

## Portfolio Replay Readiness

- status: `ready`
- missing: []
- policy_value_replay: `CAGR_FIRST_REPLAY_REQUIRED`

Event-level evidence can prioritize rules. It is not a substitute for portfolio-level CAGR/MaxDD replay.
