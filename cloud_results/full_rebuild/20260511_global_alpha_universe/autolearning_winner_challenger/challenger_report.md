# AutoLearning Winner Challenger

Research-only harness connecting AutoLearning v2 with winner lifecycle, winner onset, and shakeout/breakdown studies.

## Verdict

- `READY_FOR_PORTFOLIO_CHALLENGER_REPLAY`
- production_activation_allowed: `False`

## Baseline

- Main CAGR / Sharpe / MaxDD: 27.32% / 1.6397079003602735 / -17.87%
- Main avg/latest cash: 19.37% / 28.23%
- Concentrated CAGR / Sharpe / MaxDD: 39.86% / 1.7049580372452717 / -16.58%

## Connected Signals

- AutoLearning hypotheses: 5
- Missed winners: 30 top=['STX', 'FLEX', 'CIEN', 'AMD', 'LITE', 'BE', 'HIMX', 'MRVL']
- Stale winners: 0 top=[]
- Leadership rotations: 11 top=['TXN->LITE', 'LRCX->LITE', 'AKAM->LITE', 'MLI->MTZ', 'TKR->MTZ', 'ON->LITE', 'GLW->LITE', 'PWR->BE']
- Onset events: 28
- Shakeout/breakdown events: 1327 labels={'AMBIGUOUS': 342, 'DISTRIBUTION': 433, 'SHAKEOUT': 428, 'TRUE_BREAKDOWN': 124}
- Main cash-drag replay: available best=cash0.00_cap0.18
- Main v2 historical replay: completed
- Concentrated policy replay: completed
- Alpha Sprint historical sidecar: inactive_no_bull_months_or_candidates
- Position-aware risk replay: completed
- Monster lifecycle replay: completed policy=concentrated

## Event-Level Backtest

| Strategy | N | Median | Avg | Hit Rate | Worst | Best |
|---|---:|---:|---:|---:|---:|---:|
| hold_3m_return | 28 | 29.06% | 33.61% | 85.71% | -6.39% | 117.95% |
| hold_6m_return | 28 | 76.65% | 89.44% | 100.00% | 50.47% | 275.27% |
| hold_12m_return | 28 | 177.76% | 248.12% | 100.00% | 79.82% | 751.20% |
| hold_18m_return | 19 | 217.19% | 323.65% | 100.00% | 90.11% | 1303.74% |
| trail20_after_50pct_return | 27 | 117.35% | 167.72% | 100.00% | 32.96% | 601.56% |
| ma50_5d_after_50pct_return | 25 | 120.60% | 130.48% | 100.00% | 27.52% | 537.71% |
| ma200_after_50pct_return | 20 | 115.54% | 307.99% | 100.00% | 15.27% | 1814.23% |

## Shakeout/Breakdown Action Backtest

| Label | Horizon | Action | N | Median | Avg | Hit Rate | Worst |
|---|---|---|---:|---:|---:|---:|---:|
| AMBIGUOUS | 6m | add25 | 342 | 12.88% | 11.28% | 85.67% | -12.40% |
| AMBIGUOUS | 6m | exit_to_cash | 342 | 0.00% | 0.00% | 0.00% | 0.00% |
| AMBIGUOUS | 6m | hold | 342 | 10.31% | 9.02% | 85.67% | -9.92% |
| AMBIGUOUS | 6m | label_oracle | 342 | 5.15% | 4.51% | 85.67% | -4.96% |
| AMBIGUOUS | 6m | trim50 | 342 | 5.15% | 4.51% | 85.67% | -4.96% |
| DISTRIBUTION | 6m | add25 | 433 | -1.48% | 0.59% | 46.88% | -73.44% |
| DISTRIBUTION | 6m | exit_to_cash | 433 | 0.00% | 0.00% | 0.00% | 0.00% |
| DISTRIBUTION | 6m | hold | 433 | -1.19% | 0.48% | 46.88% | -58.75% |
| DISTRIBUTION | 6m | label_oracle | 433 | 0.00% | 0.00% | 0.00% | 0.00% |
| DISTRIBUTION | 6m | trim50 | 433 | -0.59% | 0.24% | 46.88% | -29.37% |
| SHAKEOUT | 6m | add25 | 428 | 44.88% | 58.67% | 100.00% | 25.11% |
| SHAKEOUT | 6m | exit_to_cash | 428 | 0.00% | 0.00% | 0.00% | 0.00% |
| SHAKEOUT | 6m | hold | 428 | 35.90% | 46.94% | 100.00% | 20.09% |
| SHAKEOUT | 6m | label_oracle | 428 | 44.88% | 58.67% | 100.00% | 25.11% |
| SHAKEOUT | 6m | trim50 | 428 | 17.95% | 23.47% | 100.00% | 10.05% |
| TRUE_BREAKDOWN | 6m | add25 | 124 | -22.37% | -22.92% | 12.90% | -70.38% |
| TRUE_BREAKDOWN | 6m | exit_to_cash | 124 | 0.00% | 0.00% | 0.00% | 0.00% |
| TRUE_BREAKDOWN | 6m | hold | 124 | -17.90% | -18.34% | 12.90% | -56.30% |
| TRUE_BREAKDOWN | 6m | label_oracle | 124 | 0.00% | 0.00% | 0.00% | 0.00% |
| TRUE_BREAKDOWN | 6m | trim50 | 124 | -8.95% | -9.17% | 12.90% | -28.15% |

## Portfolio Replay Readiness

- status: `ready`
- missing: []
- policy_value_replay: `CAGR_FIRST_REPLAY_REQUIRED`

Event-level evidence can prioritize rules. It is not a substitute for portfolio-level CAGR/MaxDD replay.
