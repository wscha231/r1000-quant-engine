# AutoLearning Winner Challenger

Research-only harness connecting AutoLearning v2 with winner lifecycle, winner onset, and shakeout/breakdown studies.

## Verdict

- `READY_FOR_PORTFOLIO_CHALLENGER_REPLAY`
- production_activation_allowed: `False`

## Baseline

- Main CAGR / Sharpe / MaxDD: 28.45% / 1.7143210142406808 / -18.05%
- Main avg/latest cash: 20.21% / 28.00%
- Concentrated CAGR / Sharpe / MaxDD: 47.60% / 1.7801446965137586 / -23.02%

## Connected Signals

- AutoLearning hypotheses: 6
- Missed winners: 30 top=['SNDK', 'MU', 'STX', 'HIMX', 'ALAB', 'WDC', 'BE', 'CIEN']
- Stale winners: 0 top=[]
- Leadership rotations: 13 top=['HPE->SNDK', 'MLI->BE', 'ON->SNDK', 'AMD->SNDK', 'ARM->SNDK', 'NXPI->STM', 'MRVL->SNDK', 'TKR->BE']
- Onset events: 29
- Shakeout/breakdown events: 1353 labels={'AMBIGUOUS': 325, 'DISTRIBUTION': 450, 'SHAKEOUT': 437, 'TRUE_BREAKDOWN': 141}
- Main cash-drag replay: available best=cash0.00_cap0.33
- Main v2 historical replay: completed
- Concentrated policy replay: completed
- Alpha Sprint historical sidecar: inactive_no_bull_months_or_candidates
- Position-aware risk replay: completed
- Monster lifecycle replay: completed policy=concentrated

## Event-Level Backtest

| Strategy | N | Median | Avg | Hit Rate | Worst | Best |
|---|---:|---:|---:|---:|---:|---:|
| hold_3m_return | 29 | 31.78% | 34.76% | 86.21% | -6.39% | 117.95% |
| hold_6m_return | 29 | 84.59% | 104.15% | 100.00% | 50.47% | 437.07% |
| hold_12m_return | 29 | 187.97% | 271.26% | 100.00% | 79.82% | 751.20% |
| hold_18m_return | 20 | 205.70% | 370.15% | 100.00% | 90.11% | 1336.25% |
| trail20_after_50pct_return | 27 | 119.43% | 177.60% | 100.00% | 32.96% | 601.56% |
| ma50_5d_after_50pct_return | 25 | 121.91% | 140.03% | 100.00% | 27.52% | 537.71% |
| ma200_after_50pct_return | 19 | 117.60% | 319.83% | 100.00% | 15.27% | 1814.23% |

## Shakeout/Breakdown Action Backtest

| Label | Horizon | Action | N | Median | Avg | Hit Rate | Worst |
|---|---|---|---:|---:|---:|---:|---:|
| AMBIGUOUS | 6m | add25 | 325 | 12.79% | 11.49% | 85.85% | -12.40% |
| AMBIGUOUS | 6m | exit_to_cash | 325 | 0.00% | 0.00% | 0.00% | 0.00% |
| AMBIGUOUS | 6m | hold | 325 | 10.23% | 9.19% | 85.85% | -9.92% |
| AMBIGUOUS | 6m | label_oracle | 325 | 5.11% | 4.60% | 85.85% | -4.96% |
| AMBIGUOUS | 6m | trim50 | 325 | 5.11% | 4.60% | 85.85% | -4.96% |
| DISTRIBUTION | 6m | add25 | 450 | -1.27% | 1.54% | 48.00% | -73.44% |
| DISTRIBUTION | 6m | exit_to_cash | 450 | 0.00% | 0.00% | 0.00% | 0.00% |
| DISTRIBUTION | 6m | hold | 450 | -1.01% | 1.23% | 48.00% | -58.75% |
| DISTRIBUTION | 6m | label_oracle | 450 | 0.00% | 0.00% | 0.00% | 0.00% |
| DISTRIBUTION | 6m | trim50 | 450 | -0.51% | 0.62% | 48.00% | -29.37% |
| SHAKEOUT | 6m | add25 | 437 | 45.59% | 61.61% | 100.00% | 25.11% |
| SHAKEOUT | 6m | exit_to_cash | 437 | 0.00% | 0.00% | 0.00% | 0.00% |
| SHAKEOUT | 6m | hold | 437 | 36.47% | 49.28% | 100.00% | 20.09% |
| SHAKEOUT | 6m | label_oracle | 437 | 45.59% | 61.61% | 100.00% | 25.11% |
| SHAKEOUT | 6m | trim50 | 437 | 18.24% | 24.64% | 100.00% | 10.05% |
| TRUE_BREAKDOWN | 6m | add25 | 141 | -21.95% | -22.30% | 12.77% | -70.38% |
| TRUE_BREAKDOWN | 6m | exit_to_cash | 141 | 0.00% | 0.00% | 0.00% | 0.00% |
| TRUE_BREAKDOWN | 6m | hold | 141 | -17.56% | -17.84% | 12.77% | -56.30% |
| TRUE_BREAKDOWN | 6m | label_oracle | 141 | 0.00% | 0.00% | 0.00% | 0.00% |
| TRUE_BREAKDOWN | 6m | trim50 | 141 | -8.78% | -8.92% | 12.77% | -28.15% |

## Portfolio Replay Readiness

- status: `ready`
- missing: []
- policy_value_replay: `CAGR_FIRST_REPLAY_REQUIRED`

Event-level evidence can prioritize rules. It is not a substitute for portfolio-level CAGR/MaxDD replay.
