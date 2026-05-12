# AutoLearning Winner Challenger

Research-only harness connecting AutoLearning v2 with winner lifecycle, winner onset, and shakeout/breakdown studies.

## Verdict

- `READY_FOR_PORTFOLIO_CHALLENGER_REPLAY`
- production_activation_allowed: `False`

## Baseline

- Main CAGR / Sharpe / MaxDD: 28.91% / 1.7438756765602594 / -13.56%
- Main avg/latest cash: 18.94% / 28.39%
- Concentrated CAGR / Sharpe / MaxDD: 46.68% / 1.7450442508169008 / -18.57%

## Connected Signals

- AutoLearning hypotheses: 5
- Missed winners: 30 top=['STX', 'FLEX', 'CIEN', 'AMD', 'LITE', 'BE', 'HIMX', 'STM']
- Stale winners: 1 top=['AMZN']
- Leadership rotations: 13 top=['TSM->LITE', 'NXPI->STM', 'TXN->LITE', 'LRCX->LITE', 'AKAM->LITE', 'MLI->MTZ', 'ON->LITE', 'GLW->LITE']
- Onset events: 26
- Shakeout/breakdown events: 1316 labels={'AMBIGUOUS': 339, 'DISTRIBUTION': 432, 'SHAKEOUT': 416, 'TRUE_BREAKDOWN': 129}
- Main cash-drag replay: available best=cash0.00_cap0.33
- Main v2 historical replay: completed
- Concentrated policy replay: completed
- Alpha Sprint historical sidecar: inactive_no_bull_months_or_candidates
- Position-aware risk replay: completed
- Monster lifecycle replay: completed policy=concentrated

## Event-Level Backtest

| Strategy | N | Median | Avg | Hit Rate | Worst | Best |
|---|---:|---:|---:|---:|---:|---:|
| hold_3m_return | 26 | 29.06% | 30.57% | 88.46% | -6.39% | 86.20% |
| hold_6m_return | 26 | 81.45% | 91.43% | 100.00% | 50.47% | 275.27% |
| hold_12m_return | 26 | 167.89% | 242.65% | 100.00% | 79.82% | 751.20% |
| hold_18m_return | 17 | 189.60% | 297.15% | 100.00% | 90.11% | 1303.74% |
| trail20_after_50pct_return | 25 | 117.35% | 170.46% | 100.00% | 32.96% | 601.56% |
| ma50_5d_after_50pct_return | 23 | 104.37% | 129.54% | 100.00% | 27.52% | 537.71% |
| ma200_after_50pct_return | 18 | 115.54% | 263.32% | 100.00% | 15.27% | 1814.23% |

## Shakeout/Breakdown Action Backtest

| Label | Horizon | Action | N | Median | Avg | Hit Rate | Worst |
|---|---|---|---:|---:|---:|---:|---:|
| AMBIGUOUS | 6m | add25 | 339 | 12.52% | 11.09% | 84.07% | -12.40% |
| AMBIGUOUS | 6m | exit_to_cash | 339 | 0.00% | 0.00% | 0.00% | 0.00% |
| AMBIGUOUS | 6m | hold | 339 | 10.02% | 8.87% | 84.07% | -9.92% |
| AMBIGUOUS | 6m | label_oracle | 339 | 5.01% | 4.43% | 84.07% | -4.96% |
| AMBIGUOUS | 6m | trim50 | 339 | 5.01% | 4.43% | 84.07% | -4.96% |
| DISTRIBUTION | 6m | add25 | 432 | -1.72% | 0.35% | 45.60% | -73.44% |
| DISTRIBUTION | 6m | exit_to_cash | 432 | 0.00% | 0.00% | 0.00% | 0.00% |
| DISTRIBUTION | 6m | hold | 432 | -1.38% | 0.28% | 45.60% | -58.75% |
| DISTRIBUTION | 6m | label_oracle | 432 | 0.00% | 0.00% | 0.00% | 0.00% |
| DISTRIBUTION | 6m | trim50 | 432 | -0.69% | 0.14% | 45.60% | -29.37% |
| SHAKEOUT | 6m | add25 | 416 | 43.99% | 56.40% | 100.00% | 25.11% |
| SHAKEOUT | 6m | exit_to_cash | 416 | 0.00% | 0.00% | 0.00% | 0.00% |
| SHAKEOUT | 6m | hold | 416 | 35.19% | 45.12% | 100.00% | 20.09% |
| SHAKEOUT | 6m | label_oracle | 416 | 43.99% | 56.40% | 100.00% | 25.11% |
| SHAKEOUT | 6m | trim50 | 416 | 17.60% | 22.56% | 100.00% | 10.05% |
| TRUE_BREAKDOWN | 6m | add25 | 129 | -22.40% | -23.42% | 11.63% | -70.38% |
| TRUE_BREAKDOWN | 6m | exit_to_cash | 129 | 0.00% | 0.00% | 0.00% | 0.00% |
| TRUE_BREAKDOWN | 6m | hold | 129 | -17.92% | -18.73% | 11.63% | -56.30% |
| TRUE_BREAKDOWN | 6m | label_oracle | 129 | 0.00% | 0.00% | 0.00% | 0.00% |
| TRUE_BREAKDOWN | 6m | trim50 | 129 | -8.96% | -9.37% | 11.63% | -28.15% |

## Portfolio Replay Readiness

- status: `ready`
- missing: []
- policy_value_replay: `CAGR_FIRST_REPLAY_REQUIRED`

Event-level evidence can prioritize rules. It is not a substitute for portfolio-level CAGR/MaxDD replay.
