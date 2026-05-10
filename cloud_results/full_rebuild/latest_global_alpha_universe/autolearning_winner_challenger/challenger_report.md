# AutoLearning Winner Challenger

Research-only harness connecting AutoLearning v2 with winner lifecycle, winner onset, and shakeout/breakdown studies.

## Verdict

- `READY_FOR_PORTFOLIO_CHALLENGER_REPLAY`
- production_activation_allowed: `False`

## Baseline

- Main CAGR / Sharpe / MaxDD: 28.47% / 1.6505880825201922 / -15.42%
- Main avg/latest cash: 20.25% / 28.00%
- Concentrated CAGR / Sharpe / MaxDD: 43.24% / 1.7696899020615104 / -12.59%

## Connected Signals

- AutoLearning hypotheses: 5
- Missed winners: 30 top=['STX', 'FLEX', 'CIEN', 'AMD', 'LITE', 'BE', 'HIMX', 'MRVL']
- Stale winners: 0 top=[]
- Leadership rotations: 11 top=['AMAT->LITE', 'LRCX->LITE', 'MLI->MTZ', 'AKAM->LITE', 'TKR->MTZ', 'ON->LITE', 'GLW->LITE', 'PWR->BE']
- Onset events: 29
- Shakeout/breakdown events: 1306 labels={'AMBIGUOUS': 331, 'DISTRIBUTION': 419, 'SHAKEOUT': 426, 'TRUE_BREAKDOWN': 130}
- Main cash-drag replay: available best=cash0.00_cap0.33
- Main v2 historical replay: completed
- Concentrated policy replay: completed
- Alpha Sprint historical sidecar: inactive_no_bull_months_or_candidates
- Position-aware risk replay: completed
- Monster lifecycle replay: completed policy=concentrated

## Event-Level Backtest

| Strategy | N | Median | Avg | Hit Rate | Worst | Best |
|---|---:|---:|---:|---:|---:|---:|
| hold_3m_return | 29 | 31.78% | 36.33% | 89.66% | -6.39% | 117.95% |
| hold_6m_return | 29 | 78.30% | 91.87% | 100.00% | 50.47% | 275.27% |
| hold_12m_return | 29 | 159.35% | 239.57% | 100.00% | 79.82% | 751.20% |
| hold_18m_return | 20 | 202.87% | 307.08% | 100.00% | 90.11% | 1303.74% |
| trail20_after_50pct_return | 28 | 118.39% | 166.37% | 100.00% | 32.96% | 601.56% |
| ma50_5d_after_50pct_return | 26 | 112.49% | 123.83% | 100.00% | 27.52% | 537.71% |
| ma200_after_50pct_return | 20 | 115.54% | 298.01% | 100.00% | 15.27% | 1814.23% |

## Shakeout/Breakdown Action Backtest

| Label | Horizon | Action | N | Median | Avg | Hit Rate | Worst |
|---|---|---|---:|---:|---:|---:|---:|
| AMBIGUOUS | 6m | add25 | 331 | 12.32% | 11.08% | 85.50% | -12.40% |
| AMBIGUOUS | 6m | exit_to_cash | 331 | 0.00% | 0.00% | 0.00% | 0.00% |
| AMBIGUOUS | 6m | hold | 331 | 9.85% | 8.87% | 85.50% | -9.92% |
| AMBIGUOUS | 6m | label_oracle | 331 | 4.93% | 4.43% | 85.50% | -4.96% |
| AMBIGUOUS | 6m | trim50 | 331 | 4.93% | 4.43% | 85.50% | -4.96% |
| DISTRIBUTION | 6m | add25 | 419 | -1.48% | 0.69% | 46.78% | -70.04% |
| DISTRIBUTION | 6m | exit_to_cash | 419 | 0.00% | 0.00% | 0.00% | 0.00% |
| DISTRIBUTION | 6m | hold | 419 | -1.19% | 0.55% | 46.78% | -56.03% |
| DISTRIBUTION | 6m | label_oracle | 419 | 0.00% | 0.00% | 0.00% | 0.00% |
| DISTRIBUTION | 6m | trim50 | 419 | -0.59% | 0.28% | 46.78% | -28.02% |
| SHAKEOUT | 6m | add25 | 426 | 45.10% | 58.82% | 100.00% | 25.09% |
| SHAKEOUT | 6m | exit_to_cash | 426 | 0.00% | 0.00% | 0.00% | 0.00% |
| SHAKEOUT | 6m | hold | 426 | 36.08% | 47.06% | 100.00% | 20.07% |
| SHAKEOUT | 6m | label_oracle | 426 | 45.10% | 58.82% | 100.00% | 25.09% |
| SHAKEOUT | 6m | trim50 | 426 | 18.04% | 23.53% | 100.00% | 10.03% |
| TRUE_BREAKDOWN | 6m | add25 | 130 | -22.19% | -22.74% | 12.31% | -70.38% |
| TRUE_BREAKDOWN | 6m | exit_to_cash | 130 | 0.00% | 0.00% | 0.00% | 0.00% |
| TRUE_BREAKDOWN | 6m | hold | 130 | -17.75% | -18.19% | 12.31% | -56.30% |
| TRUE_BREAKDOWN | 6m | label_oracle | 130 | 0.00% | 0.00% | 0.00% | 0.00% |
| TRUE_BREAKDOWN | 6m | trim50 | 130 | -8.88% | -9.10% | 12.31% | -28.15% |

## Portfolio Replay Readiness

- status: `ready`
- missing: []
- policy_value_replay: `CAGR_FIRST_REPLAY_REQUIRED`

Event-level evidence can prioritize rules. It is not a substitute for portfolio-level CAGR/MaxDD replay.
