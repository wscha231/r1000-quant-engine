# Cash Policy Attribution

Research-only diagnostic. No production weights are changed.

## Summary

- months: 83
- avg reported cash: 19.72%
- avg explicit CASH in monthly book: 4.32%
- avg reported-vs-book cash gap: 15.40%
- avg target defense cash: 4.00%
- avg excess cash over target: 15.72%
- months reported cash >20%: 29
- months reported cash >50%: 6
- months possible idle cash: 61
- months with cash export mismatch >2pp: 74

## Primary Reason Counts

| reason | months | cash-weight sum |
|---|---:|---:|
| `cap_limited_leftover` | 2 | 9.35% |
| `cash_export_mismatch` | 67 | 1320.28% |
| `confirmed_macro_defense_cash` | 6 | 218.34% |
| `mixed_confirmed_macro_and_idle_cash` | 2 | 86.14% |
| `no_cash` | 4 | 0.00% |
| `partial_rebalance_leftover` | 2 | 2.79% |

## Largest Cash Months

| date | reported cash | book cash | gap | target | regime | action | reason | idle? | stocks / target |
|---|---:|---:|---:|---:|---|---|---|---:|---:|
| 2020-02-28 | 80.83% | 28.00% | 52.83% | 28.00% | risk_off_alert | rebalance | `cash_export_mismatch` | false | 18 / 18.0 |
| 2025-02-28 | 77.59% | 23.68% | 53.91% | 28.00% | risk_off_alert | partial_rebalance:core_compounder,early_scout | `cash_export_mismatch` | false | 44 / 18.0 |
| 2022-03-31 | 70.83% | 0.00% | 70.83% | 0.00% | growth_reentry_alert | partial_rebalance:core_compounder,early_scout | `cash_export_mismatch` | true | 18 / 18.0 |
| 2025-10-31 | 66.74% | 0.00% | 66.74% | 0.00% | balanced | partial_rebalance:core_compounder,early_scout | `cash_export_mismatch` | true | 25 / 18.0 |
| 2026-02-27 | 65.56% | 28.21% | 37.35% | 28.00% | risk_off_alert | partial_rebalance:core_compounder,early_scout | `cash_export_mismatch` | false | 27 / 18.0 |
| 2022-05-31 | 54.24% | 0.00% | 54.24% | 0.00% | balanced | circuit_breaker_rebalance | `cash_export_mismatch` | true | 30 / 18.0 |
| 2023-08-31 | 48.19% | 0.00% | 48.19% | 0.00% | balanced | partial_rebalance:core_compounder,early_scout | `cash_export_mismatch` | true | 18 / 18.0 |
| 2021-01-29 | 45.96% | 28.00% | 17.96% | 28.00% | risk_off_alert | partial_rebalance:core_compounder,early_scout | `mixed_confirmed_macro_and_idle_cash` | false | 17 / 18.0 |
| 2023-09-29 | 44.10% | 40.00% | 4.10% | 40.00% | systemic_alert | rebalance | `confirmed_macro_defense_cash` | false | 17 / 18.0 |
| 2024-07-31 | 40.78% | 40.00% | 0.78% | 40.00% | systemic_alert | rebalance | `confirmed_macro_defense_cash` | false | 18 / 18.0 |
| 2021-02-26 | 40.18% | 28.00% | 12.18% | 28.00% | risk_off_alert | rebalance | `mixed_confirmed_macro_and_idle_cash` | false | 17 / 18.0 |
| 2026-01-30 | 38.22% | 0.00% | 38.22% | 0.00% | balanced | rebalance | `cash_export_mismatch` | true | 17 / 18.0 |

## Largest Possible Idle-Cash Months

| date | reported cash | book cash | gap | target | regime | action | reason | stocks / target |
|---|---:|---:|---:|---:|---|---|---|---:|
| 2022-03-31 | 70.83% | 0.00% | 70.83% | 0.00% | growth_reentry_alert | partial_rebalance:core_compounder,early_scout | `cash_export_mismatch` | 18 / 18.0 |
| 2025-10-31 | 66.74% | 0.00% | 66.74% | 0.00% | balanced | partial_rebalance:core_compounder,early_scout | `cash_export_mismatch` | 25 / 18.0 |
| 2022-05-31 | 54.24% | 0.00% | 54.24% | 0.00% | balanced | circuit_breaker_rebalance | `cash_export_mismatch` | 30 / 18.0 |
| 2023-08-31 | 48.19% | 0.00% | 48.19% | 0.00% | balanced | partial_rebalance:core_compounder,early_scout | `cash_export_mismatch` | 18 / 18.0 |
| 2026-01-30 | 38.22% | 0.00% | 38.22% | 0.00% | balanced | rebalance | `cash_export_mismatch` | 17 / 18.0 |
| 2021-12-31 | 37.94% | 0.00% | 37.94% | 0.00% | balanced | rebalance | `cash_export_mismatch` | 17 / 18.0 |
| 2024-06-28 | 33.48% | 0.00% | 33.48% | 0.00% | balanced | partial_rebalance:core_compounder,early_scout | `cash_export_mismatch` | 33 / 18.0 |
| 2021-08-31 | 32.95% | 0.00% | 32.95% | 0.00% | balanced | rebalance | `cash_export_mismatch` | 36 / 18.0 |
| 2025-06-30 | 32.06% | 0.00% | 32.06% | 0.00% | balanced | partial_rebalance:core_compounder,early_scout | `cash_export_mismatch` | 18 / 18.0 |
| 2020-01-31 | 30.31% | 0.00% | 30.31% | 0.00% | balanced | partial_rebalance:core_compounder,early_scout | `cash_export_mismatch` | 18 / 18.0 |
| 2024-03-28 | 29.83% | 1.55% | 28.28% | 0.00% | balanced | rebalance | `cash_export_mismatch` | 18 / 18.0 |
| 2024-11-29 | 28.15% | 0.00% | 28.15% | 0.00% | growth_reentry_alert | rebalance | `cash_export_mismatch` | 47 / 18.0 |

## Interpretation

- Defense cash should be preserved in crisis/red regimes.
- Large defense cash should require confirmed macro deterioration, not a one-off event shock.
- Non-risk excess cash is the candidate pool for the next idle-cash redeploy A/B.
- If reported cash and explicit monthly-book cash diverge, downstream replays must use the reported cash source or the monthly book should be repaired.
