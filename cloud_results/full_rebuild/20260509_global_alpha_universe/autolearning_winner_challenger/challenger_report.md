# AutoLearning Winner Challenger

Research-only harness connecting AutoLearning v2 with winner lifecycle, winner onset, and shakeout/breakdown studies.

## Verdict

- `READY_FOR_PORTFOLIO_CHALLENGER_REPLAY`
- production_activation_allowed: `False`

## Baseline

- Main CAGR / Sharpe / MaxDD: 30.91% / 1.6999187026810325 / -16.38%
- Main avg/latest cash: 22.04% / 27.87%
- Concentrated CAGR / Sharpe / MaxDD: 49.80% / 1.7607009713417816 / -17.24%

## Connected Signals

- AutoLearning hypotheses: 6
- Missed winners: 30 top=['MU', 'STX', 'FLEX', 'LITE', 'CIEN', 'AMD', 'BE', 'HIMX']
- Stale winners: 0 top=[]
- Leadership rotations: 13 top=['HPE->LITE', 'ENTG->LITE', 'LRCX->LITE', 'AKAM->LITE', 'MLI->MTZ', 'TKR->MTZ', 'MRVL->LITE', 'ON->LITE']
- Onset events: 33
- Shakeout/breakdown events: 1351 labels={'AMBIGUOUS': 328, 'DISTRIBUTION': 462, 'SHAKEOUT': 430, 'TRUE_BREAKDOWN': 131}
- Main cash-drag replay: available best=cash0.00_cap0.18
- Main v2 historical replay: completed
- Concentrated policy replay: completed
- Alpha Sprint historical sidecar: inactive_no_bull_months_or_candidates
- Position-aware risk replay: completed
- Monster lifecycle replay: completed policy=concentrated

## Event-Level Backtest

| Strategy | N | Median | Avg | Hit Rate | Worst | Best |
|---|---:|---:|---:|---:|---:|---:|
| hold_3m_return | 33 | 35.14% | 36.12% | 90.91% | -6.39% | 117.95% |
| hold_6m_return | 33 | 82.45% | 101.94% | 100.00% | 50.47% | 437.07% |
| hold_12m_return | 33 | 159.35% | 245.22% | 100.00% | 79.82% | 751.20% |
| hold_18m_return | 24 | 206.22% | 332.42% | 100.00% | 65.06% | 1336.25% |
| trail20_after_50pct_return | 32 | 119.78% | 171.95% | 100.00% | 32.96% | 601.56% |
| ma50_5d_after_50pct_return | 30 | 118.77% | 131.80% | 100.00% | 27.52% | 537.71% |
| ma200_after_50pct_return | 23 | 123.86% | 281.05% | 100.00% | 15.27% | 1814.23% |

## Shakeout/Breakdown Action Backtest

| Label | Horizon | Action | N | Median | Avg | Hit Rate | Worst |
|---|---|---|---:|---:|---:|---:|---:|
| AMBIGUOUS | 6m | add25 | 328 | 12.99% | 11.29% | 85.06% | -12.40% |
| AMBIGUOUS | 6m | exit_to_cash | 328 | 0.00% | 0.00% | 0.00% | 0.00% |
| AMBIGUOUS | 6m | hold | 328 | 10.39% | 9.03% | 85.06% | -9.92% |
| AMBIGUOUS | 6m | label_oracle | 328 | 5.20% | 4.52% | 85.06% | -4.96% |
| AMBIGUOUS | 6m | trim50 | 328 | 5.20% | 4.52% | 85.06% | -4.96% |
| DISTRIBUTION | 6m | add25 | 462 | -1.63% | 0.83% | 46.10% | -73.44% |
| DISTRIBUTION | 6m | exit_to_cash | 462 | 0.00% | 0.00% | 0.00% | 0.00% |
| DISTRIBUTION | 6m | hold | 462 | -1.30% | 0.66% | 46.10% | -58.75% |
| DISTRIBUTION | 6m | label_oracle | 462 | 0.00% | 0.00% | 0.00% | 0.00% |
| DISTRIBUTION | 6m | trim50 | 462 | -0.65% | 0.33% | 46.10% | -29.37% |
| SHAKEOUT | 6m | add25 | 430 | 45.04% | 60.62% | 100.00% | 25.09% |
| SHAKEOUT | 6m | exit_to_cash | 430 | 0.00% | 0.00% | 0.00% | 0.00% |
| SHAKEOUT | 6m | hold | 430 | 36.03% | 48.50% | 100.00% | 20.07% |
| SHAKEOUT | 6m | label_oracle | 430 | 45.04% | 60.62% | 100.00% | 25.09% |
| SHAKEOUT | 6m | trim50 | 430 | 18.02% | 24.25% | 100.00% | 10.03% |
| TRUE_BREAKDOWN | 6m | add25 | 131 | -22.40% | -23.16% | 12.21% | -70.38% |
| TRUE_BREAKDOWN | 6m | exit_to_cash | 131 | 0.00% | 0.00% | 0.00% | 0.00% |
| TRUE_BREAKDOWN | 6m | hold | 131 | -17.92% | -18.53% | 12.21% | -56.30% |
| TRUE_BREAKDOWN | 6m | label_oracle | 131 | 0.00% | 0.00% | 0.00% | 0.00% |
| TRUE_BREAKDOWN | 6m | trim50 | 131 | -8.96% | -9.26% | 12.21% | -28.15% |

## Portfolio Replay Readiness

- status: `ready`
- missing: []
- policy_value_replay: `CAGR_FIRST_REPLAY_REQUIRED`

Event-level evidence can prioritize rules. It is not a substitute for portfolio-level CAGR/MaxDD replay.
