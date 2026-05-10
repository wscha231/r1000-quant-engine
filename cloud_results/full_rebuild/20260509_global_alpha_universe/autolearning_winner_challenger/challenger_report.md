# AutoLearning Winner Challenger

Research-only harness connecting AutoLearning v2 with winner lifecycle, winner onset, and shakeout/breakdown studies.

## Verdict

- `READY_FOR_PORTFOLIO_CHALLENGER_REPLAY`
- production_activation_allowed: `False`

## Baseline

- Main CAGR / Sharpe / MaxDD: 27.86% / 1.6498608070881968 / -16.84%
- Main avg/latest cash: 20.16% / 28.05%
- Concentrated CAGR / Sharpe / MaxDD: 45.90% / 1.9039986545320031 / -13.46%

## Connected Signals

- AutoLearning hypotheses: 6
- Missed winners: 30 top=['MU', 'STX', 'FLEX', 'CIEN', 'AMD', 'LITE', 'BE', 'HIMX']
- Stale winners: 0 top=[]
- Leadership rotations: 14 top=['LRCX->LITE', 'AKAM->LITE', 'MLI->MTZ', 'TKR->MTZ', 'MRVL->LITE', 'ON->LITE', 'GLW->LITE', 'NXPI->UMC']
- Onset events: 25
- Shakeout/breakdown events: 1313 labels={'AMBIGUOUS': 342, 'DISTRIBUTION': 431, 'SHAKEOUT': 413, 'TRUE_BREAKDOWN': 127}
- Main cash-drag replay: available best=cash0.00_cap0.18
- Main v2 historical replay: completed
- Concentrated policy replay: completed
- Alpha Sprint historical sidecar: inactive_no_bull_months_or_candidates
- Position-aware risk replay: completed
- Monster lifecycle replay: completed policy=concentrated

## Event-Level Backtest

| Strategy | N | Median | Avg | Hit Rate | Worst | Best |
|---|---:|---:|---:|---:|---:|---:|
| hold_3m_return | 25 | 28.02% | 30.59% | 88.00% | -6.39% | 86.20% |
| hold_6m_return | 25 | 78.30% | 91.61% | 100.00% | 50.47% | 275.27% |
| hold_12m_return | 25 | 176.44% | 246.33% | 100.00% | 79.82% | 751.20% |
| hold_18m_return | 16 | 203.40% | 306.10% | 100.00% | 90.11% | 1303.74% |
| trail20_after_50pct_return | 24 | 116.94% | 172.58% | 100.00% | 32.96% | 601.56% |
| ma50_5d_after_50pct_return | 22 | 112.49% | 132.73% | 100.00% | 27.52% | 537.71% |
| ma200_after_50pct_return | 17 | 117.60% | 272.49% | 100.00% | 15.27% | 1814.23% |

## Shakeout/Breakdown Action Backtest

| Label | Horizon | Action | N | Median | Avg | Hit Rate | Worst |
|---|---|---|---:|---:|---:|---:|---:|
| AMBIGUOUS | 6m | add25 | 342 | 12.54% | 11.17% | 85.09% | -12.40% |
| AMBIGUOUS | 6m | exit_to_cash | 342 | 0.00% | 0.00% | 0.00% | 0.00% |
| AMBIGUOUS | 6m | hold | 342 | 10.03% | 8.93% | 85.09% | -9.92% |
| AMBIGUOUS | 6m | label_oracle | 342 | 5.02% | 4.47% | 85.09% | -4.96% |
| AMBIGUOUS | 6m | trim50 | 342 | 5.02% | 4.47% | 85.09% | -4.96% |
| DISTRIBUTION | 6m | add25 | 431 | -1.03% | 0.95% | 47.10% | -70.04% |
| DISTRIBUTION | 6m | exit_to_cash | 431 | 0.00% | 0.00% | 0.00% | 0.00% |
| DISTRIBUTION | 6m | hold | 431 | -0.83% | 0.76% | 47.10% | -56.03% |
| DISTRIBUTION | 6m | label_oracle | 431 | 0.00% | 0.00% | 0.00% | 0.00% |
| DISTRIBUTION | 6m | trim50 | 431 | -0.41% | 0.38% | 47.10% | -28.02% |
| SHAKEOUT | 6m | add25 | 413 | 44.42% | 56.60% | 100.00% | 25.11% |
| SHAKEOUT | 6m | exit_to_cash | 413 | 0.00% | 0.00% | 0.00% | 0.00% |
| SHAKEOUT | 6m | hold | 413 | 35.54% | 45.28% | 100.00% | 20.09% |
| SHAKEOUT | 6m | label_oracle | 413 | 44.42% | 56.60% | 100.00% | 25.11% |
| SHAKEOUT | 6m | trim50 | 413 | 17.77% | 22.64% | 100.00% | 10.05% |
| TRUE_BREAKDOWN | 6m | add25 | 127 | -22.54% | -24.05% | 10.24% | -72.54% |
| TRUE_BREAKDOWN | 6m | exit_to_cash | 127 | 0.00% | 0.00% | 0.00% | 0.00% |
| TRUE_BREAKDOWN | 6m | hold | 127 | -18.03% | -19.24% | 10.24% | -58.03% |
| TRUE_BREAKDOWN | 6m | label_oracle | 127 | 0.00% | 0.00% | 0.00% | 0.00% |
| TRUE_BREAKDOWN | 6m | trim50 | 127 | -9.02% | -9.62% | 10.24% | -29.01% |

## Portfolio Replay Readiness

- status: `ready`
- missing: []
- policy_value_replay: `CAGR_FIRST_REPLAY_REQUIRED`

Event-level evidence can prioritize rules. It is not a substitute for portfolio-level CAGR/MaxDD replay.
