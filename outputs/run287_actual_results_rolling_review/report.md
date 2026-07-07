# Run287 Actual Results Rolling Review

- Status: `completed`
- Decision label: `mixed_headline_pass_oos_cagr_worse`
- Candidate arm: `actual_results_top_quintile_tilt10`
- Metric mode: `broker_ledger_next_close_cash_carry`
- Replay end date: `2026-07-06`
- Runner parity status: `parity_documented_gap`
- Survivorship label: `proxy`
- Measurement acceptance allowed: `False`
- No fullrun, hook, threshold tuning, production promotion, or live trading.

## Fixed Windows

| Window | Candidate CAGR | Candidate MaxDD | dCAGR pp | dMDD pp | Contract pass |
| --- | ---: | ---: | ---: | ---: | --- |
| full | 35.45% | -24.59% | +1.20 | +0.77 | True |
| is_to_2024_06_30 | 25.49% | -24.59% | +2.78 | +0.77 | False |
| oos_from_2024_07_01 | 65.37% | -21.48% | -4.06 | -0.86 | True |
| oos2_from_2023_01_01 | 49.86% | -21.48% | +0.42 | -0.86 | True |

## Rolling Summary

| Group | Windows | Positive CAGR delta rate | Median dCAGR pp | Min dCAGR pp | Median dMDD pp |
| --- | ---: | ---: | ---: | ---: | ---: |
| rolling_12m | 77 | 70.13% | +1.87 | -14.98 | +0.30 |
| rolling_24m | 68 | 88.24% | +1.92 | -4.46 | +0.30 |
| rolling_36m | 59 | 94.92% | +2.01 | -0.21 | +0.30 |

## Interpretation

- Full-window result restores the Main headline contract: 35.45% CAGR / -24.59% MDD.
- OOS CAGR delta is -4.06 pp, so the result is not accepted as a hook/fullrun candidate.
- Measurement-contract blockers: `runner_parity_not_exact`.
- This remains default-off research evidence only.
