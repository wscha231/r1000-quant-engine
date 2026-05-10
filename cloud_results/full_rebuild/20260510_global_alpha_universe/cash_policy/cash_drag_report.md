# Cash Policy Attribution

Research-only diagnostic. No production weights are changed.

## Summary

- months: 83
- avg reported cash: 20.25%
- avg explicit CASH in monthly book: 4.29%
- avg reported-vs-book cash gap: 15.96%
- avg target defense cash: 4.00%
- avg excess cash over target: 16.25%
- months reported cash >20%: 30
- months reported cash >50%: 6
- months possible idle cash: 63
- months with cash export mismatch >2pp: 77

## Primary Reason Counts

| reason | months | cash-weight sum |
|---|---:|---:|
| `cap_limited_leftover` | 2 | 12.02% |
| `cash_export_mismatch` | 69 | 1360.43% |
| `confirmed_macro_defense_cash` | 6 | 215.33% |
| `mixed_confirmed_macro_and_idle_cash` | 2 | 92.65% |
| `no_cash` | 4 | 0.28% |

## Largest Cash Months

| date | reported cash | book cash | gap | target | regime | action | reason | idle? | stocks / target |
|---|---:|---:|---:|---:|---|---|---|---:|---:|
| 2020-02-28 | 84.98% | 28.00% | 56.98% | 28.00% | risk_off_alert | rebalance | `cash_export_mismatch` | false | 18 / 18.0 |
| 2025-02-28 | 75.80% | 23.58% | 52.22% | 28.00% | risk_off_alert | partial_rebalance:core_compounder,early_scout | `cash_export_mismatch` | false | 43 / 18.0 |
| 2026-02-27 | 69.62% | 28.00% | 41.62% | 28.00% | risk_off_alert | partial_rebalance:core_compounder,early_scout | `cash_export_mismatch` | false | 18 / 18.0 |
| 2022-03-31 | 68.82% | 0.00% | 68.82% | 0.00% | growth_reentry_alert | partial_rebalance:core_compounder,early_scout | `cash_export_mismatch` | true | 36 / 18.0 |
| 2022-05-31 | 67.02% | 0.00% | 67.02% | 0.00% | balanced | circuit_breaker_rebalance | `cash_export_mismatch` | true | 35 / 18.0 |
| 2025-10-31 | 58.68% | 0.00% | 58.68% | 0.00% | balanced | partial_rebalance:core_compounder,early_scout | `cash_export_mismatch` | true | 24 / 18.0 |
| 2021-01-29 | 49.04% | 28.00% | 21.04% | 28.00% | risk_off_alert | partial_rebalance:core_compounder,early_scout | `mixed_confirmed_macro_and_idle_cash` | false | 17 / 18.0 |
| 2023-08-31 | 47.41% | 0.00% | 47.41% | 0.00% | balanced | partial_rebalance:core_compounder,early_scout | `cash_export_mismatch` | true | 18 / 18.0 |
| 2023-09-29 | 44.28% | 40.00% | 4.28% | 40.00% | systemic_alert | rebalance | `confirmed_macro_defense_cash` | false | 18 / 18.0 |
| 2021-02-26 | 43.61% | 28.00% | 15.61% | 28.00% | risk_off_alert | rebalance | `mixed_confirmed_macro_and_idle_cash` | false | 17 / 18.0 |
| 2024-07-31 | 42.88% | 40.00% | 2.88% | 40.00% | systemic_alert | rebalance | `confirmed_macro_defense_cash` | false | 18 / 18.0 |
| 2024-03-28 | 34.87% | 0.00% | 34.87% | 0.00% | balanced | rebalance | `cash_export_mismatch` | true | 18 / 18.0 |

## Largest Possible Idle-Cash Months

| date | reported cash | book cash | gap | target | regime | action | reason | stocks / target |
|---|---:|---:|---:|---:|---|---|---|---:|
| 2022-03-31 | 68.82% | 0.00% | 68.82% | 0.00% | growth_reentry_alert | partial_rebalance:core_compounder,early_scout | `cash_export_mismatch` | 36 / 18.0 |
| 2022-05-31 | 67.02% | 0.00% | 67.02% | 0.00% | balanced | circuit_breaker_rebalance | `cash_export_mismatch` | 35 / 18.0 |
| 2025-10-31 | 58.68% | 0.00% | 58.68% | 0.00% | balanced | partial_rebalance:core_compounder,early_scout | `cash_export_mismatch` | 24 / 18.0 |
| 2023-08-31 | 47.41% | 0.00% | 47.41% | 0.00% | balanced | partial_rebalance:core_compounder,early_scout | `cash_export_mismatch` | 18 / 18.0 |
| 2024-03-28 | 34.87% | 0.00% | 34.87% | 0.00% | balanced | rebalance | `cash_export_mismatch` | 18 / 18.0 |
| 2024-06-28 | 34.12% | 3.95% | 30.17% | 0.00% | balanced | partial_rebalance:core_compounder,early_scout | `cash_export_mismatch` | 18 / 18.0 |
| 2021-12-31 | 32.84% | 0.00% | 32.84% | 0.00% | balanced | rebalance | `cash_export_mismatch` | 28 / 18.0 |
| 2026-01-30 | 32.37% | 0.00% | 32.37% | 0.00% | balanced | rebalance | `cash_export_mismatch` | 38 / 18.0 |
| 2025-06-30 | 31.22% | 0.00% | 31.22% | 0.00% | balanced | partial_rebalance:core_compounder,early_scout | `cash_export_mismatch` | 18 / 18.0 |
| 2023-04-28 | 30.56% | 0.00% | 30.56% | 0.00% | balanced | partial_rebalance:core_compounder,early_scout | `cash_export_mismatch` | 18 / 18.0 |
| 2021-03-31 | 29.08% | 0.00% | 29.08% | 0.00% | growth_reentry_alert | partial_rebalance:core_compounder,early_scout | `cash_export_mismatch` | 26 / 18.0 |
| 2024-11-29 | 28.88% | 0.00% | 28.88% | 0.00% | growth_reentry_alert | rebalance | `cash_export_mismatch` | 50 / 18.0 |

## Interpretation

- Defense cash should be preserved in crisis/red regimes.
- Large defense cash should require confirmed macro deterioration, not a one-off event shock.
- Non-risk excess cash is the candidate pool for the next idle-cash redeploy A/B.
- If reported cash and explicit monthly-book cash diverge, downstream replays must use the reported cash source or the monthly book should be repaired.
