# AutoLearning Winner Challenger

Research-only harness connecting AutoLearning v2 with winner lifecycle, winner onset, and shakeout/breakdown studies.

## Verdict

- `READY_FOR_PORTFOLIO_CHALLENGER_REPLAY`
- production_activation_allowed: `False`

## Baseline

- Main CAGR / Sharpe / MaxDD: 30.87% / 1.7202960298994148 / -18.51%
- Main avg/latest cash: 21.41% / 28.00%
- Concentrated CAGR / Sharpe / MaxDD: 47.95% / 1.7573547279957327 / -14.06%

## Connected Signals

- AutoLearning hypotheses: 6
- Missed winners: 30 top=['SNDK', 'INTC', 'STX', 'LITE', 'HIMX', 'RKLB', 'FLEX', 'CIEN']
- Stale winners: 1 top=['TKR']
- Leadership rotations: 13 top=['HPE->SNDK', 'AMD->SNDK', 'MRVL->SNDK', 'ON->SNDK', 'MLI->RKLB', 'TKR->RKLB', 'WDC->SNDK', 'GEV->RKLB']
- Onset events: 30
- Shakeout/breakdown events: 1340 labels={'AMBIGUOUS': 336, 'DISTRIBUTION': 457, 'SHAKEOUT': 417, 'TRUE_BREAKDOWN': 130}
- Main cash-drag replay: available best=cash0.00_cap0.33
- Main v2 historical replay: completed
- Concentrated policy replay: completed
- Alpha Sprint historical sidecar: completed
- Position-aware risk replay: completed
- Monster lifecycle replay: completed policy=concentrated

## Event-Level Backtest

| Strategy | N | Median | Avg | Hit Rate | Worst | Best |
|---|---:|---:|---:|---:|---:|---:|
| hold_3m_return | 30 | 25.55% | 29.89% | 80.00% | -34.51% | 117.95% |
| hold_6m_return | 30 | 76.50% | 88.98% | 100.00% | 50.47% | 275.27% |
| hold_12m_return | 30 | 186.87% | 269.27% | 100.00% | 79.82% | 751.20% |
| hold_18m_return | 21 | 221.80% | 323.92% | 100.00% | 90.11% | 1303.74% |
| trail20_after_50pct_return | 29 | 119.43% | 174.63% | 100.00% | 32.96% | 601.56% |
| ma50_5d_after_50pct_return | 27 | 121.21% | 136.52% | 100.00% | 27.52% | 537.71% |
| ma200_after_50pct_return | 21 | 139.92% | 323.37% | 100.00% | 15.27% | 1814.23% |

## Shakeout/Breakdown Action Backtest

| Label | Horizon | Action | N | Median | Avg | Hit Rate | Worst |
|---|---|---|---:|---:|---:|---:|---:|
| AMBIGUOUS | 6m | add25 | 336 | 12.30% | 10.84% | 83.93% | -12.40% |
| AMBIGUOUS | 6m | exit_to_cash | 336 | 0.00% | 0.00% | 0.00% | 0.00% |
| AMBIGUOUS | 6m | hold | 336 | 9.84% | 8.68% | 83.93% | -9.92% |
| AMBIGUOUS | 6m | label_oracle | 336 | 4.92% | 4.34% | 83.93% | -4.96% |
| AMBIGUOUS | 6m | trim50 | 336 | 4.92% | 4.34% | 83.93% | -4.96% |
| DISTRIBUTION | 6m | add25 | 457 | -0.45% | 1.26% | 49.02% | -73.44% |
| DISTRIBUTION | 6m | exit_to_cash | 457 | 0.00% | 0.00% | 0.00% | 0.00% |
| DISTRIBUTION | 6m | hold | 457 | -0.36% | 1.01% | 49.02% | -58.75% |
| DISTRIBUTION | 6m | label_oracle | 457 | 0.00% | 0.00% | 0.00% | 0.00% |
| DISTRIBUTION | 6m | trim50 | 457 | -0.18% | 0.51% | 49.02% | -29.37% |
| SHAKEOUT | 6m | add25 | 417 | 45.49% | 61.02% | 100.00% | 25.11% |
| SHAKEOUT | 6m | exit_to_cash | 417 | 0.00% | 0.00% | 0.00% | 0.00% |
| SHAKEOUT | 6m | hold | 417 | 36.40% | 48.82% | 100.00% | 20.09% |
| SHAKEOUT | 6m | label_oracle | 417 | 45.49% | 61.02% | 100.00% | 25.11% |
| SHAKEOUT | 6m | trim50 | 417 | 18.20% | 24.41% | 100.00% | 10.05% |
| TRUE_BREAKDOWN | 6m | add25 | 130 | -21.89% | -22.15% | 14.62% | -70.38% |
| TRUE_BREAKDOWN | 6m | exit_to_cash | 130 | 0.00% | 0.00% | 0.00% | 0.00% |
| TRUE_BREAKDOWN | 6m | hold | 130 | -17.51% | -17.72% | 14.62% | -56.30% |
| TRUE_BREAKDOWN | 6m | label_oracle | 130 | 0.00% | 0.00% | 0.00% | 0.00% |
| TRUE_BREAKDOWN | 6m | trim50 | 130 | -8.76% | -8.86% | 14.62% | -28.15% |

## Portfolio Replay Readiness

- status: `ready`
- missing: []
- policy_value_replay: `CAGR_FIRST_REPLAY_REQUIRED`

Event-level evidence can prioritize rules. It is not a substitute for portfolio-level CAGR/MaxDD replay.
