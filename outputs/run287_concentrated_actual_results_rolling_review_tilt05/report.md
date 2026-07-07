# Run287 Actual Results Rolling Review

- Status: `completed`
- Decision label: `reject_headline_contract_not_restored`
- Candidate arm: `actual_results_top_quintile_tilt05`
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
| full | 48.28% | -23.19% | -0.38 | -0.24 | False |
| is_to_2024_06_30 | 28.13% | -20.58% | +0.56 | +0.25 | False |
| oos_from_2024_07_01 | 115.20% | -23.19% | -4.41 | -0.24 | True |
| oos2_from_2023_01_01 | 73.45% | -23.19% | -0.97 | -0.24 | True |

## Rolling Summary

| Group | Windows | Positive CAGR delta rate | Median dCAGR pp | Min dCAGR pp | Median dMDD pp |
| --- | ---: | ---: | ---: | ---: | ---: |
| rolling_12m | 77 | 44.16% | -0.14 | -20.24 | +0.21 |
| rolling_24m | 68 | 60.29% | +0.14 | -5.40 | +0.10 |
| rolling_36m | 59 | 64.41% | +0.18 | -1.70 | -0.21 |

## Interpretation

- Full-window contract pass: `False` at 48.28% CAGR / -23.19% MDD.
- OOS CAGR delta is -4.41 pp, so the result is not accepted as a hook/fullrun candidate.
- Measurement-contract blockers: `runner_parity_not_exact`.
- This remains default-off research evidence only.
