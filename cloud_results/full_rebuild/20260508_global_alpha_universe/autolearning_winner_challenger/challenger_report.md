# AutoLearning Winner Challenger

Research-only harness connecting AutoLearning v2 with winner lifecycle, winner onset, and shakeout/breakdown studies.

## Verdict

- `READY_FOR_PORTFOLIO_CHALLENGER_REPLAY`
- production_activation_allowed: `False`

## Baseline

- Main CAGR / Sharpe / MaxDD: 28.12% / 1.6202096991237043 / -15.92%
- Main avg/latest cash: 19.72% / 28.21%
- Concentrated CAGR / Sharpe / MaxDD: 47.71% / 1.749531723854578 / -19.72%

## Connected Signals

- AutoLearning hypotheses: 6
- Missed winners: 30 top=['LITE', 'STX', 'MU', 'FLEX', 'BE', 'MRVL', 'AMD', 'AMKR']
- Stale winners: 0 top=[]
- Leadership rotations: 16 top=['AMAT->LITE', 'LRCX->LITE', 'TER->LITE', 'ON->LITE', 'NXPI->STM', 'GLW->LITE', 'MLI->MTZ', 'TKR->MTZ']
- Onset events: 28
- Shakeout/breakdown events: 1316 labels={'AMBIGUOUS': 343, 'DISTRIBUTION': 416, 'SHAKEOUT': 430, 'TRUE_BREAKDOWN': 127}
- Main cash-drag replay: available best=cash0.00_cap0.18
- Main v2 historical replay: completed
- Concentrated policy replay: completed
- Alpha Sprint historical sidecar: inactive_no_bull_months_or_candidates
- Position-aware risk replay: completed
- Monster lifecycle replay: completed policy=concentrated

## Event-Level Backtest

| Strategy | N | Median | Avg | Hit Rate | Worst | Best |
|---|---:|---:|---:|---:|---:|---:|
| hold_3m_return | 28 | 30.94% | 32.22% | 89.29% | -6.39% | 86.20% |
| hold_6m_return | 28 | 76.65% | 89.96% | 100.00% | 50.47% | 275.27% |
| hold_12m_return | 28 | 155.11% | 230.26% | 100.00% | 79.82% | 751.20% |
| hold_18m_return | 19 | 189.60% | 280.51% | 100.00% | 90.11% | 1303.74% |
| trail20_after_50pct_return | 27 | 117.35% | 162.52% | 100.00% | 32.96% | 601.56% |
| ma50_5d_after_50pct_return | 25 | 104.37% | 122.99% | 100.00% | 27.52% | 537.71% |
| ma200_after_50pct_return | 19 | 117.60% | 255.08% | 100.00% | 15.27% | 1814.23% |

## Shakeout/Breakdown Action Backtest

| Label | Horizon | Action | N | Median | Avg | Hit Rate | Worst |
|---|---|---|---:|---:|---:|---:|---:|
| AMBIGUOUS | 6m | add25 | 343 | 12.79% | 11.30% | 86.30% | -12.25% |
| AMBIGUOUS | 6m | exit_to_cash | 343 | 0.00% | 0.00% | 0.00% | 0.00% |
| AMBIGUOUS | 6m | hold | 343 | 10.23% | 9.04% | 86.30% | -9.80% |
| AMBIGUOUS | 6m | label_oracle | 343 | 5.11% | 4.52% | 86.30% | -4.90% |
| AMBIGUOUS | 6m | trim50 | 343 | 5.11% | 4.52% | 86.30% | -4.90% |
| DISTRIBUTION | 6m | add25 | 416 | -1.01% | 0.66% | 47.12% | -70.04% |
| DISTRIBUTION | 6m | exit_to_cash | 416 | 0.00% | 0.00% | 0.00% | 0.00% |
| DISTRIBUTION | 6m | hold | 416 | -0.81% | 0.53% | 47.12% | -56.03% |
| DISTRIBUTION | 6m | label_oracle | 416 | 0.00% | 0.00% | 0.00% | 0.00% |
| DISTRIBUTION | 6m | trim50 | 416 | -0.40% | 0.26% | 47.12% | -28.02% |
| SHAKEOUT | 6m | add25 | 430 | 44.88% | 56.55% | 100.00% | 25.09% |
| SHAKEOUT | 6m | exit_to_cash | 430 | 0.00% | 0.00% | 0.00% | 0.00% |
| SHAKEOUT | 6m | hold | 430 | 35.90% | 45.24% | 100.00% | 20.07% |
| SHAKEOUT | 6m | label_oracle | 430 | 44.88% | 56.55% | 100.00% | 25.09% |
| SHAKEOUT | 6m | trim50 | 430 | 17.95% | 22.62% | 100.00% | 10.03% |
| TRUE_BREAKDOWN | 6m | add25 | 127 | -22.04% | -23.15% | 11.81% | -70.38% |
| TRUE_BREAKDOWN | 6m | exit_to_cash | 127 | 0.00% | 0.00% | 0.00% | 0.00% |
| TRUE_BREAKDOWN | 6m | hold | 127 | -17.63% | -18.52% | 11.81% | -56.30% |
| TRUE_BREAKDOWN | 6m | label_oracle | 127 | 0.00% | 0.00% | 0.00% | 0.00% |
| TRUE_BREAKDOWN | 6m | trim50 | 127 | -8.82% | -9.26% | 11.81% | -28.15% |

## Portfolio Replay Readiness

- status: `ready`
- missing: []
- policy_value_replay: `CAGR_FIRST_REPLAY_REQUIRED`

Event-level evidence can prioritize rules. It is not a substitute for portfolio-level CAGR/MaxDD replay.
