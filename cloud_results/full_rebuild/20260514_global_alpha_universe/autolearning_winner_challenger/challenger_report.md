# AutoLearning Winner Challenger

Research-only harness connecting AutoLearning v2 with winner lifecycle, winner onset, and shakeout/breakdown studies.

## Verdict

- `READY_FOR_PORTFOLIO_CHALLENGER_REPLAY`
- production_activation_allowed: `False`

## Baseline

- Main CAGR / Sharpe / MaxDD: 30.62% / 1.687330574762984 / -16.88%
- Main avg/latest cash: 21.99% / 28.00%
- Concentrated CAGR / Sharpe / MaxDD: 56.30% / 1.8844929489164732 / -14.83%

## Connected Signals

- AutoLearning hypotheses: 6
- Missed winners: 30 top=['SNDK', 'INTC', 'STX', 'RKLB', 'LITE', 'PL', 'HIMX', 'BE']
- Stale winners: 0 top=[]
- Leadership rotations: 12 top=['HPE->SNDK', 'LRCX->SNDK', 'MLI->BE', 'TKR->BE', 'AMD->SNDK', 'ON->SNDK', 'MRVL->SNDK', 'PWR->BE']
- Onset events: 30
- Shakeout/breakdown events: 1332 labels={'AMBIGUOUS': 337, 'DISTRIBUTION': 447, 'SHAKEOUT': 422, 'TRUE_BREAKDOWN': 126}
- Main cash-drag replay: available best=cash0.00_cap0.18
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
| AMBIGUOUS | 6m | add25 | 337 | 12.29% | 10.94% | 84.27% | -12.40% |
| AMBIGUOUS | 6m | exit_to_cash | 337 | 0.00% | 0.00% | 0.00% | 0.00% |
| AMBIGUOUS | 6m | hold | 337 | 9.83% | 8.75% | 84.27% | -9.92% |
| AMBIGUOUS | 6m | label_oracle | 337 | 4.92% | 4.37% | 84.27% | -4.96% |
| AMBIGUOUS | 6m | trim50 | 337 | 4.92% | 4.37% | 84.27% | -4.96% |
| DISTRIBUTION | 6m | add25 | 447 | -1.36% | 0.53% | 47.43% | -73.44% |
| DISTRIBUTION | 6m | exit_to_cash | 447 | 0.00% | 0.00% | 0.00% | 0.00% |
| DISTRIBUTION | 6m | hold | 447 | -1.09% | 0.42% | 47.43% | -58.75% |
| DISTRIBUTION | 6m | label_oracle | 447 | 0.00% | 0.00% | 0.00% | 0.00% |
| DISTRIBUTION | 6m | trim50 | 447 | -0.54% | 0.21% | 47.43% | -29.37% |
| SHAKEOUT | 6m | add25 | 422 | 45.54% | 60.78% | 100.00% | 25.11% |
| SHAKEOUT | 6m | exit_to_cash | 422 | 0.00% | 0.00% | 0.00% | 0.00% |
| SHAKEOUT | 6m | hold | 422 | 36.43% | 48.62% | 100.00% | 20.09% |
| SHAKEOUT | 6m | label_oracle | 422 | 45.54% | 60.78% | 100.00% | 25.11% |
| SHAKEOUT | 6m | trim50 | 422 | 18.22% | 24.31% | 100.00% | 10.05% |
| TRUE_BREAKDOWN | 6m | add25 | 126 | -22.60% | -22.60% | 15.08% | -70.38% |
| TRUE_BREAKDOWN | 6m | exit_to_cash | 126 | 0.00% | 0.00% | 0.00% | 0.00% |
| TRUE_BREAKDOWN | 6m | hold | 126 | -18.08% | -18.08% | 15.08% | -56.30% |
| TRUE_BREAKDOWN | 6m | label_oracle | 126 | 0.00% | 0.00% | 0.00% | 0.00% |
| TRUE_BREAKDOWN | 6m | trim50 | 126 | -9.04% | -9.04% | 15.08% | -28.15% |

## Portfolio Replay Readiness

- status: `ready`
- missing: []
- policy_value_replay: `CAGR_FIRST_REPLAY_REQUIRED`

Event-level evidence can prioritize rules. It is not a substitute for portfolio-level CAGR/MaxDD replay.
