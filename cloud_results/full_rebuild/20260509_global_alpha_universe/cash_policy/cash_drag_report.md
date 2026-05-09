# Cash Policy Attribution

Research-only diagnostic. No production weights are changed.

## Summary

- months: 83
- avg reported cash: 20.16%
- avg explicit CASH in monthly book: 4.67%
- avg reported-vs-book cash gap: 15.49%
- avg target defense cash: 4.41%
- avg excess cash over target: 15.76%
- months reported cash >20%: 33
- months reported cash >50%: 7
- months possible idle cash: 57
- months with cash export mismatch >2pp: 74

## Primary Reason Counts

| reason | months | cash-weight sum |
|---|---:|---:|
| `cap_limited_leftover` | 3 | 22.76% |
| `cash_export_mismatch` | 64 | 1312.41% |
| `confirmed_macro_defense_cash` | 7 | 244.88% |
| `mixed_confirmed_macro_and_idle_cash` | 2 | 93.61% |
| `no_cash` | 7 | 0.00% |

## Largest Cash Months

| date | reported cash | book cash | gap | target | regime | action | reason | idle? | stocks / target |
|---|---:|---:|---:|---:|---|---|---|---:|---:|
| 2020-02-28 | 78.75% | 28.00% | 50.75% | 28.00% | risk_off_alert | rebalance | `cash_export_mismatch` | false | 18 / 18.0 |
| 2025-02-28 | 75.75% | 25.05% | 50.71% | 28.00% | risk_off_alert | partial_rebalance:core_compounder,early_scout | `cash_export_mismatch` | false | 45 / 18.0 |
| 2022-03-31 | 74.85% | 0.00% | 74.85% | 0.00% | growth_reentry_alert | circuit_breaker_release | `cash_export_mismatch` | true | 18 / 18.0 |
| 2026-02-27 | 71.96% | 28.05% | 43.91% | 28.00% | risk_off_alert | partial_rebalance:core_compounder,early_scout | `cash_export_mismatch` | false | 28 / 18.0 |
| 2022-05-31 | 61.39% | 0.00% | 61.39% | 0.00% | balanced | circuit_breaker_rebalance | `cash_export_mismatch` | false | 29 / 18.0 |
| 2021-12-31 | 59.57% | 0.00% | 59.57% | 0.00% | balanced | rebalance | `cash_export_mismatch` | true | 17 / 18.0 |
| 2025-10-31 | 53.24% | 0.00% | 53.24% | 0.00% | balanced | partial_rebalance:core_compounder,early_scout | `cash_export_mismatch` | true | 24 / 18.0 |
| 2021-01-29 | 48.97% | 28.00% | 20.97% | 28.00% | risk_off_alert | partial_rebalance:core_compounder,early_scout | `mixed_confirmed_macro_and_idle_cash` | false | 17 / 18.0 |
| 2023-08-31 | 44.91% | 0.00% | 44.91% | 0.00% | balanced | partial_rebalance:core_compounder,early_scout | `cash_export_mismatch` | true | 18 / 18.0 |
| 2021-02-26 | 44.64% | 28.00% | 16.64% | 28.00% | risk_off_alert | rebalance | `mixed_confirmed_macro_and_idle_cash` | false | 17 / 18.0 |
| 2023-09-29 | 43.10% | 40.00% | 3.10% | 40.00% | systemic_alert | rebalance | `confirmed_macro_defense_cash` | false | 18 / 18.0 |
| 2024-07-31 | 42.37% | 40.00% | 2.37% | 40.00% | systemic_alert | rebalance | `confirmed_macro_defense_cash` | false | 18 / 18.0 |

## Largest Possible Idle-Cash Months

| date | reported cash | book cash | gap | target | regime | action | reason | stocks / target |
|---|---:|---:|---:|---:|---|---|---|---:|
| 2022-03-31 | 74.85% | 0.00% | 74.85% | 0.00% | growth_reentry_alert | circuit_breaker_release | `cash_export_mismatch` | 18 / 18.0 |
| 2021-12-31 | 59.57% | 0.00% | 59.57% | 0.00% | balanced | rebalance | `cash_export_mismatch` | 17 / 18.0 |
| 2025-10-31 | 53.24% | 0.00% | 53.24% | 0.00% | balanced | partial_rebalance:core_compounder,early_scout | `cash_export_mismatch` | 24 / 18.0 |
| 2023-08-31 | 44.91% | 0.00% | 44.91% | 0.00% | balanced | partial_rebalance:core_compounder,early_scout | `cash_export_mismatch` | 18 / 18.0 |
| 2024-03-28 | 33.43% | 0.00% | 33.43% | 0.00% | balanced | rebalance | `cash_export_mismatch` | 18 / 18.0 |
| 2024-11-29 | 33.07% | 1.08% | 31.99% | 0.00% | growth_reentry_alert | rebalance | `cash_export_mismatch` | 51 / 18.0 |
| 2026-01-30 | 29.61% | 0.00% | 29.61% | 0.00% | balanced | rebalance | `cash_export_mismatch` | 17 / 18.0 |
| 2024-06-28 | 27.71% | 3.96% | 23.76% | 0.00% | balanced | partial_rebalance:core_compounder,early_scout | `cash_export_mismatch` | 33 / 18.0 |
| 2021-10-29 | 27.30% | 0.00% | 27.30% | 0.00% | growth_reentry_alert | rebalance | `cash_export_mismatch` | 25 / 18.0 |
| 2025-06-30 | 26.95% | 0.00% | 26.95% | 0.00% | balanced | partial_rebalance:core_compounder,early_scout | `cash_export_mismatch` | 18 / 18.0 |
| 2021-03-31 | 26.20% | 0.00% | 26.20% | 0.00% | growth_reentry_alert | partial_rebalance:core_compounder,early_scout | `cash_export_mismatch` | 26 / 18.0 |
| 2021-08-31 | 26.07% | 0.00% | 26.07% | 0.00% | balanced | rebalance | `cash_export_mismatch` | 32 / 18.0 |

## Interpretation

- Defense cash should be preserved in crisis/red regimes.
- Large defense cash should require confirmed macro deterioration, not a one-off event shock.
- Non-risk excess cash is the candidate pool for the next idle-cash redeploy A/B.
- If reported cash and explicit monthly-book cash diverge, downstream replays must use the reported cash source or the monthly book should be repaired.
