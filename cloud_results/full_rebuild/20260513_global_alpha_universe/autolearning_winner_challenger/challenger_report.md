# AutoLearning Winner Challenger

Research-only harness connecting AutoLearning v2 with winner lifecycle, winner onset, and shakeout/breakdown studies.

## Verdict

- `READY_FOR_PORTFOLIO_CHALLENGER_REPLAY`
- production_activation_allowed: `False`

## Baseline

- Main CAGR / Sharpe / MaxDD: 28.31% / 1.682607622313662 / -16.24%
- Main avg/latest cash: 19.21% / 28.00%
- Concentrated CAGR / Sharpe / MaxDD: 48.19% / 1.8368841417296249 / -16.36%

## Connected Signals

- AutoLearning hypotheses: 4
- Missed winners: 30 top=['SNDK', 'STX', 'LITE', 'CIEN', 'FLEX', 'HIMX', 'BE', 'AMD']
- Stale winners: 2 top=['PLTR', 'AMZN']
- Leadership rotations: 11 top=['PLTR->SNDK', 'AKAM->SNDK', 'LRCX->SNDK', 'ON->SNDK', 'GLW->SNDK', 'NXPI->STM', 'MLI->BE', 'AMZN->MUSA']
- Onset events: 29
- Shakeout/breakdown events: 1298 labels={'AMBIGUOUS': 328, 'DISTRIBUTION': 434, 'SHAKEOUT': 405, 'TRUE_BREAKDOWN': 131}
- Main cash-drag replay: available best=cash0.00_cap0.33
- Main v2 historical replay: completed
- Concentrated policy replay: completed
- Alpha Sprint historical sidecar: completed
- Position-aware risk replay: completed
- Monster lifecycle replay: completed policy=concentrated

## Event-Level Backtest

| Strategy | N | Median | Avg | Hit Rate | Worst | Best |
|---|---:|---:|---:|---:|---:|---:|
| hold_3m_return | 29 | 31.78% | 35.55% | 89.66% | -6.39% | 117.95% |
| hold_6m_return | 29 | 84.59% | 103.97% | 100.00% | 50.47% | 437.07% |
| hold_12m_return | 29 | 179.09% | 259.23% | 100.00% | 79.82% | 751.20% |
| hold_18m_return | 20 | 219.49% | 369.81% | 100.00% | 90.11% | 1336.25% |
| trail20_after_50pct_return | 28 | 119.78% | 181.54% | 100.00% | 32.96% | 601.56% |
| ma50_5d_after_50pct_return | 26 | 120.91% | 136.70% | 100.00% | 27.52% | 537.71% |
| ma200_after_50pct_return | 20 | 115.54% | 301.69% | 100.00% | 15.27% | 1814.23% |

## Shakeout/Breakdown Action Backtest

| Label | Horizon | Action | N | Median | Avg | Hit Rate | Worst |
|---|---|---|---:|---:|---:|---:|---:|
| AMBIGUOUS | 6m | add25 | 328 | 12.45% | 11.09% | 84.45% | -12.40% |
| AMBIGUOUS | 6m | exit_to_cash | 328 | 0.00% | 0.00% | 0.00% | 0.00% |
| AMBIGUOUS | 6m | hold | 328 | 9.96% | 8.87% | 84.45% | -9.92% |
| AMBIGUOUS | 6m | label_oracle | 328 | 4.98% | 4.44% | 84.45% | -4.96% |
| AMBIGUOUS | 6m | trim50 | 328 | 4.98% | 4.44% | 84.45% | -4.96% |
| DISTRIBUTION | 6m | add25 | 434 | -1.42% | 1.15% | 47.00% | -73.44% |
| DISTRIBUTION | 6m | exit_to_cash | 434 | 0.00% | 0.00% | 0.00% | 0.00% |
| DISTRIBUTION | 6m | hold | 434 | -1.14% | 0.92% | 47.00% | -58.75% |
| DISTRIBUTION | 6m | label_oracle | 434 | 0.00% | 0.00% | 0.00% | 0.00% |
| DISTRIBUTION | 6m | trim50 | 434 | -0.57% | 0.46% | 47.00% | -29.37% |
| SHAKEOUT | 6m | add25 | 405 | 45.15% | 60.38% | 100.00% | 25.11% |
| SHAKEOUT | 6m | exit_to_cash | 405 | 0.00% | 0.00% | 0.00% | 0.00% |
| SHAKEOUT | 6m | hold | 405 | 36.12% | 48.30% | 100.00% | 20.09% |
| SHAKEOUT | 6m | label_oracle | 405 | 45.15% | 60.38% | 100.00% | 25.11% |
| SHAKEOUT | 6m | trim50 | 405 | 18.06% | 24.15% | 100.00% | 10.05% |
| TRUE_BREAKDOWN | 6m | add25 | 131 | -21.95% | -22.78% | 10.69% | -70.38% |
| TRUE_BREAKDOWN | 6m | exit_to_cash | 131 | 0.00% | 0.00% | 0.00% | 0.00% |
| TRUE_BREAKDOWN | 6m | hold | 131 | -17.56% | -18.23% | 10.69% | -56.30% |
| TRUE_BREAKDOWN | 6m | label_oracle | 131 | 0.00% | 0.00% | 0.00% | 0.00% |
| TRUE_BREAKDOWN | 6m | trim50 | 131 | -8.78% | -9.11% | 10.69% | -28.15% |

## Portfolio Replay Readiness

- status: `ready`
- missing: []
- policy_value_replay: `CAGR_FIRST_REPLAY_REQUIRED`

Event-level evidence can prioritize rules. It is not a substitute for portfolio-level CAGR/MaxDD replay.
