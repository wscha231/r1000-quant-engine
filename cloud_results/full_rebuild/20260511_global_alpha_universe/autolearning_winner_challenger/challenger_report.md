# AutoLearning Winner Challenger

Research-only harness connecting AutoLearning v2 with winner lifecycle, winner onset, and shakeout/breakdown studies.

## Verdict

- `READY_FOR_PORTFOLIO_CHALLENGER_REPLAY`
- production_activation_allowed: `False`

## Baseline

- Main CAGR / Sharpe / MaxDD: 29.66% / 1.7776333218625067 / -15.66%
- Main avg/latest cash: 20.63% / 28.38%
- Concentrated CAGR / Sharpe / MaxDD: 43.52% / 1.7435623649459715 / -12.51%

## Connected Signals

- AutoLearning hypotheses: 6
- Missed winners: 30 top=['STX', 'FLEX', 'CIEN', 'AMD', 'LITE', 'BE', 'HIMX', 'STM']
- Stale winners: 1 top=['NXPI']
- Leadership rotations: 15 top=['HPE->LITE', 'ENTG->LITE', 'NXPI->STM', 'TXN->LITE', 'LRCX->LITE', 'AKAM->LITE', 'MLI->MTZ', 'TKR->MTZ']
- Onset events: 28
- Shakeout/breakdown events: 1330 labels={'AMBIGUOUS': 332, 'DISTRIBUTION': 443, 'SHAKEOUT': 425, 'TRUE_BREAKDOWN': 130}
- Main cash-drag replay: available best=cash0.00_cap0.18
- Main v2 historical replay: completed
- Concentrated policy replay: completed
- Alpha Sprint historical sidecar: inactive_no_bull_months_or_candidates
- Position-aware risk replay: completed
- Monster lifecycle replay: completed policy=concentrated

## Event-Level Backtest

| Strategy | N | Median | Avg | Hit Rate | Worst | Best |
|---|---:|---:|---:|---:|---:|---:|
| hold_3m_return | 28 | 29.90% | 32.91% | 85.71% | -34.51% | 117.95% |
| hold_6m_return | 28 | 76.65% | 90.90% | 100.00% | 50.47% | 275.27% |
| hold_12m_return | 28 | 182.43% | 260.98% | 100.00% | 79.82% | 751.20% |
| hold_18m_return | 19 | 221.80% | 332.63% | 100.00% | 90.11% | 1303.74% |
| trail20_after_50pct_return | 27 | 117.35% | 170.93% | 100.00% | 30.97% | 601.56% |
| ma50_5d_after_50pct_return | 25 | 121.21% | 136.76% | 100.00% | 27.52% | 537.71% |
| ma200_after_50pct_return | 20 | 128.76% | 322.25% | 100.00% | 15.27% | 1814.23% |

## Shakeout/Breakdown Action Backtest

| Label | Horizon | Action | N | Median | Avg | Hit Rate | Worst |
|---|---|---|---:|---:|---:|---:|---:|
| AMBIGUOUS | 6m | add25 | 332 | 12.30% | 11.07% | 85.24% | -12.40% |
| AMBIGUOUS | 6m | exit_to_cash | 332 | 0.00% | 0.00% | 0.00% | 0.00% |
| AMBIGUOUS | 6m | hold | 332 | 9.84% | 8.86% | 85.24% | -9.92% |
| AMBIGUOUS | 6m | label_oracle | 332 | 4.92% | 4.43% | 85.24% | -4.96% |
| AMBIGUOUS | 6m | trim50 | 332 | 4.92% | 4.43% | 85.24% | -4.96% |
| DISTRIBUTION | 6m | add25 | 443 | -1.61% | 0.48% | 46.05% | -73.44% |
| DISTRIBUTION | 6m | exit_to_cash | 443 | 0.00% | 0.00% | 0.00% | 0.00% |
| DISTRIBUTION | 6m | hold | 443 | -1.28% | 0.38% | 46.05% | -58.75% |
| DISTRIBUTION | 6m | label_oracle | 443 | 0.00% | 0.00% | 0.00% | 0.00% |
| DISTRIBUTION | 6m | trim50 | 443 | -0.64% | 0.19% | 46.05% | -29.37% |
| SHAKEOUT | 6m | add25 | 425 | 44.85% | 59.18% | 100.00% | 25.11% |
| SHAKEOUT | 6m | exit_to_cash | 425 | 0.00% | 0.00% | 0.00% | 0.00% |
| SHAKEOUT | 6m | hold | 425 | 35.88% | 47.35% | 100.00% | 20.09% |
| SHAKEOUT | 6m | label_oracle | 425 | 44.85% | 59.18% | 100.00% | 25.11% |
| SHAKEOUT | 6m | trim50 | 425 | 17.94% | 23.67% | 100.00% | 10.05% |
| TRUE_BREAKDOWN | 6m | add25 | 130 | -22.37% | -23.37% | 12.31% | -70.38% |
| TRUE_BREAKDOWN | 6m | exit_to_cash | 130 | 0.00% | 0.00% | 0.00% | 0.00% |
| TRUE_BREAKDOWN | 6m | hold | 130 | -17.90% | -18.69% | 12.31% | -56.30% |
| TRUE_BREAKDOWN | 6m | label_oracle | 130 | 0.00% | 0.00% | 0.00% | 0.00% |
| TRUE_BREAKDOWN | 6m | trim50 | 130 | -8.95% | -9.35% | 12.31% | -28.15% |

## Portfolio Replay Readiness

- status: `ready`
- missing: []
- policy_value_replay: `CAGR_FIRST_REPLAY_REQUIRED`

Event-level evidence can prioritize rules. It is not a substitute for portfolio-level CAGR/MaxDD replay.
