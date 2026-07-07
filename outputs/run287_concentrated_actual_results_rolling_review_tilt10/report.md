# Run287 Actual Results Rolling Review

- Status: `completed`
- Decision label: `reject_headline_contract_not_restored`
- Candidate arm: `actual_results_top_quintile_tilt10`
- Portfolio: `concentrated`
- Target CAGR: `50%`
- Metric mode: `broker_ledger_next_close_cash_carry`
- Replay end date: `2026-07-06`
- Runner parity status: `parity_documented_gap`
- Survivorship label: `proxy`
- Measurement acceptance allowed: `False`
- No fullrun, hook, threshold tuning, production promotion, or live trading.

## Fixed Windows

| Window | Candidate CAGR | Candidate MaxDD | dCAGR pp | dMDD pp | Contract pass |
| --- | ---: | ---: | ---: | ---: | --- |
| full | 47.81% | -23.39% | -0.85 | -0.43 | False |
| is_to_2024_06_30 | 28.60% | -20.31% | +1.03 | +0.53 | False |
| oos_from_2024_07_01 | 110.86% | -23.39% | -8.75 | -0.43 | True |
| oos2_from_2023_01_01 | 72.27% | -23.39% | -2.15 | -0.43 | True |

## Rolling Summary

| Group | Windows | Positive CAGR delta rate | Median dCAGR pp | Min dCAGR pp | Median dMDD pp |
| --- | ---: | ---: | ---: | ---: | ---: |
| rolling_12m | 77 | 44.16% | -0.28 | -38.97 | +0.41 |
| rolling_24m | 68 | 58.82% | +0.27 | -10.67 | +0.25 |
| rolling_36m | 59 | 62.71% | +0.31 | -3.63 | -0.39 |

## Interpretation

- Full-window contract pass: `False` at 47.81% CAGR / -23.39% MDD.
- OOS CAGR delta is -8.75 pp, so the result is not accepted as a hook/fullrun candidate.
- Measurement-contract blockers: `runner_parity_not_exact`.
- This remains default-off research evidence only.
