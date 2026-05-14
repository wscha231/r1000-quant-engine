# AutoLearning Winner Challenger

Research-only harness connecting AutoLearning v2 with winner lifecycle, winner onset, and shakeout/breakdown studies.

## Verdict

- `READY_FOR_PORTFOLIO_CHALLENGER_REPLAY`
- production_activation_allowed: `False`

## Baseline

- Main CAGR / Sharpe / MaxDD: 30.99% / 1.7070972870997103 / -17.41%
- Main avg/latest cash: 21.05% / 28.01%
- Concentrated CAGR / Sharpe / MaxDD: 55.12% / 1.7167511376775713 / -14.00%

## Connected Signals

- AutoLearning hypotheses: 6
- Missed winners: 30 top=['SNDK', 'INTC', 'STX', 'LITE', 'HIMX', 'RKLB', 'FLEX', 'PL']
- Stale winners: 2 top=['NXPI', 'TKR']
- Leadership rotations: 12 top=['HPE->SNDK', 'LRCX->SNDK', 'MRVL->SNDK', 'ON->SNDK', 'MLI->RKLB', 'TKR->RKLB', 'WDC->SNDK', 'GEV->RKLB']
- Onset events: 29
- Shakeout/breakdown events: 1350 labels={'AMBIGUOUS': 333, 'DISTRIBUTION': 453, 'SHAKEOUT': 434, 'TRUE_BREAKDOWN': 130}
- Main cash-drag replay: available best=cash0.00_cap0.18
- Main v2 historical replay: completed
- Concentrated policy replay: completed
- Alpha Sprint historical sidecar: completed
- Position-aware risk replay: completed
- Monster lifecycle replay: completed policy=concentrated

## Event-Level Backtest

| Strategy | N | Median | Avg | Hit Rate | Worst | Best |
|---|---:|---:|---:|---:|---:|---:|
| hold_3m_return | 29 | 28.02% | 32.12% | 82.76% | -6.39% | 117.95% |
| hold_6m_return | 29 | 78.01% | 90.19% | 100.00% | 50.47% | 275.27% |
| hold_12m_return | 29 | 185.77% | 261.04% | 100.00% | 79.82% | 751.20% |
| hold_18m_return | 20 | 219.49% | 319.41% | 100.00% | 90.11% | 1303.74% |
| trail20_after_50pct_return | 28 | 118.39% | 169.77% | 100.00% | 32.96% | 601.56% |
| ma50_5d_after_50pct_return | 26 | 120.91% | 132.65% | 100.00% | 27.52% | 537.71% |
| ma200_after_50pct_return | 20 | 128.76% | 313.61% | 100.00% | 15.27% | 1814.23% |

## Shakeout/Breakdown Action Backtest

| Label | Horizon | Action | N | Median | Avg | Hit Rate | Worst |
|---|---|---|---:|---:|---:|---:|---:|
| AMBIGUOUS | 6m | add25 | 333 | 12.98% | 11.16% | 85.29% | -12.40% |
| AMBIGUOUS | 6m | exit_to_cash | 333 | 0.00% | 0.00% | 0.00% | 0.00% |
| AMBIGUOUS | 6m | hold | 333 | 10.38% | 8.93% | 85.29% | -9.92% |
| AMBIGUOUS | 6m | label_oracle | 333 | 5.19% | 4.47% | 85.29% | -4.96% |
| AMBIGUOUS | 6m | trim50 | 333 | 5.19% | 4.47% | 85.29% | -4.96% |
| DISTRIBUTION | 6m | add25 | 453 | -1.48% | 0.13% | 47.24% | -73.44% |
| DISTRIBUTION | 6m | exit_to_cash | 453 | 0.00% | 0.00% | 0.00% | 0.00% |
| DISTRIBUTION | 6m | hold | 453 | -1.19% | 0.10% | 47.24% | -58.75% |
| DISTRIBUTION | 6m | label_oracle | 453 | 0.00% | 0.00% | 0.00% | 0.00% |
| DISTRIBUTION | 6m | trim50 | 453 | -0.59% | 0.05% | 47.24% | -29.37% |
| SHAKEOUT | 6m | add25 | 434 | 45.59% | 59.34% | 100.00% | 25.11% |
| SHAKEOUT | 6m | exit_to_cash | 434 | 0.00% | 0.00% | 0.00% | 0.00% |
| SHAKEOUT | 6m | hold | 434 | 36.47% | 47.47% | 100.00% | 20.09% |
| SHAKEOUT | 6m | label_oracle | 434 | 45.59% | 59.34% | 100.00% | 25.11% |
| SHAKEOUT | 6m | trim50 | 434 | 18.24% | 23.74% | 100.00% | 10.05% |
| TRUE_BREAKDOWN | 6m | add25 | 130 | -22.91% | -22.93% | 13.85% | -70.38% |
| TRUE_BREAKDOWN | 6m | exit_to_cash | 130 | 0.00% | 0.00% | 0.00% | 0.00% |
| TRUE_BREAKDOWN | 6m | hold | 130 | -18.33% | -18.35% | 13.85% | -56.30% |
| TRUE_BREAKDOWN | 6m | label_oracle | 130 | 0.00% | 0.00% | 0.00% | 0.00% |
| TRUE_BREAKDOWN | 6m | trim50 | 130 | -9.17% | -9.17% | 13.85% | -28.15% |

## Portfolio Replay Readiness

- status: `ready`
- missing: []
- policy_value_replay: `CAGR_FIRST_REPLAY_REQUIRED`

Event-level evidence can prioritize rules. It is not a substitute for portfolio-level CAGR/MaxDD replay.
