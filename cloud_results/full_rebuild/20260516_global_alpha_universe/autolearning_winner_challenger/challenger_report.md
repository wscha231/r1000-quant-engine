# AutoLearning Winner Challenger

Research-only harness connecting AutoLearning v2 with winner lifecycle, winner onset, and shakeout/breakdown studies.

## Verdict

- `READY_FOR_PORTFOLIO_CHALLENGER_REPLAY`
- production_activation_allowed: `False`

## Baseline

- Main CAGR / Sharpe / MaxDD: 20.29% / 1.4848607897809738 / -15.28%
- Main avg/latest cash: 19.39% / 28.70%
- Concentrated CAGR / Sharpe / MaxDD: 28.11% / 1.583793078975827 / -11.45%

## Connected Signals

- AutoLearning hypotheses: 5
- Missed winners: 30 top=['SNDK', 'INTC', 'STX', 'HIMX', 'LITE', 'RKLB', 'WDC', 'PL']
- Stale winners: 3 top=['PLTR', 'APP', 'AMZN']
- Leadership rotations: 15 top=['PLTR->SNDK', 'APP->SNDK', 'MLI->RKLB', 'VRT->SNDK', 'ON->SNDK', 'NXPI->STM', 'CAT->RKLB', 'NVT->RKLB']
- Onset events: 27
- Shakeout/breakdown events: 1279 labels={'AMBIGUOUS': 349, 'DISTRIBUTION': 404, 'SHAKEOUT': 413, 'TRUE_BREAKDOWN': 113}
- Main cash-drag replay: available best=cash0.00_cap0.18
- Main v2 historical replay: completed
- Concentrated policy replay: completed
- Alpha Sprint historical sidecar: completed
- Position-aware risk replay: completed
- Monster lifecycle replay: completed policy=concentrated

## Event-Level Backtest

| Strategy | N | Median | Avg | Hit Rate | Worst | Best |
|---|---:|---:|---:|---:|---:|---:|
| hold_3m_return | 27 | 31.78% | 36.38% | 88.89% | -6.39% | 117.95% |
| hold_6m_return | 27 | 84.59% | 93.09% | 100.00% | 50.47% | 275.27% |
| hold_12m_return | 27 | 179.09% | 252.37% | 100.00% | 79.82% | 751.20% |
| hold_18m_return | 19 | 189.60% | 312.36% | 100.00% | 90.11% | 1303.74% |
| trail20_after_50pct_return | 25 | 117.35% | 171.86% | 100.00% | 32.96% | 601.56% |
| ma50_5d_after_50pct_return | 23 | 104.37% | 117.63% | 100.00% | 27.52% | 537.71% |
| ma200_after_50pct_return | 19 | 117.60% | 312.19% | 100.00% | 15.27% | 1814.23% |

## Shakeout/Breakdown Action Backtest

| Label | Horizon | Action | N | Median | Avg | Hit Rate | Worst |
|---|---|---|---:|---:|---:|---:|---:|
| AMBIGUOUS | 6m | add25 | 349 | 12.70% | 11.37% | 86.25% | -12.40% |
| AMBIGUOUS | 6m | exit_to_cash | 349 | 0.00% | 0.00% | 0.00% | 0.00% |
| AMBIGUOUS | 6m | hold | 349 | 10.16% | 9.10% | 86.25% | -9.92% |
| AMBIGUOUS | 6m | label_oracle | 349 | 5.08% | 4.55% | 86.25% | -4.96% |
| AMBIGUOUS | 6m | trim50 | 349 | 5.08% | 4.55% | 86.25% | -4.96% |
| DISTRIBUTION | 6m | add25 | 404 | -0.90% | 0.99% | 48.02% | -73.44% |
| DISTRIBUTION | 6m | exit_to_cash | 404 | 0.00% | 0.00% | 0.00% | 0.00% |
| DISTRIBUTION | 6m | hold | 404 | -0.72% | 0.79% | 48.02% | -58.75% |
| DISTRIBUTION | 6m | label_oracle | 404 | 0.00% | 0.00% | 0.00% | 0.00% |
| DISTRIBUTION | 6m | trim50 | 404 | -0.36% | 0.40% | 48.02% | -29.37% |
| SHAKEOUT | 6m | add25 | 413 | 44.42% | 56.69% | 100.00% | 25.11% |
| SHAKEOUT | 6m | exit_to_cash | 413 | 0.00% | 0.00% | 0.00% | 0.00% |
| SHAKEOUT | 6m | hold | 413 | 35.54% | 45.35% | 100.00% | 20.09% |
| SHAKEOUT | 6m | label_oracle | 413 | 44.42% | 56.69% | 100.00% | 25.11% |
| SHAKEOUT | 6m | trim50 | 413 | 17.77% | 22.68% | 100.00% | 10.05% |
| TRUE_BREAKDOWN | 6m | add25 | 113 | -22.04% | -22.54% | 12.39% | -72.54% |
| TRUE_BREAKDOWN | 6m | exit_to_cash | 113 | 0.00% | 0.00% | 0.00% | 0.00% |
| TRUE_BREAKDOWN | 6m | hold | 113 | -17.63% | -18.04% | 12.39% | -58.03% |
| TRUE_BREAKDOWN | 6m | label_oracle | 113 | 0.00% | 0.00% | 0.00% | 0.00% |
| TRUE_BREAKDOWN | 6m | trim50 | 113 | -8.82% | -9.02% | 12.39% | -29.01% |

## Portfolio Replay Readiness

- status: `ready`
- missing: []
- policy_value_replay: `CAGR_FIRST_REPLAY_REQUIRED`

Event-level evidence can prioritize rules. It is not a substitute for portfolio-level CAGR/MaxDD replay.
