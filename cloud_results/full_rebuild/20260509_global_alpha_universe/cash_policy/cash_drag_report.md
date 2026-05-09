# Cash Policy Attribution

Research-only diagnostic. No production weights are changed.

## Summary

- months: 83
- avg reported cash: 22.04%
- avg explicit CASH in monthly book: 4.83%
- avg reported-vs-book cash gap: 17.21%
- avg target defense cash: 4.48%
- avg excess cash over target: 17.56%
- months reported cash >20%: 32
- months reported cash >50%: 7
- months possible idle cash: 61
- months with cash export mismatch >2pp: 73

## Primary Reason Counts

| reason | months | cash-weight sum |
|---|---:|---:|
| `cash_export_mismatch` | 66 | 1415.44% |
| `confirmed_macro_defense_cash` | 7 | 255.31% |
| `mixed_confirmed_macro_and_idle_cash` | 3 | 157.41% |
| `no_cash` | 6 | 0.34% |
| `partial_rebalance_leftover` | 1 | 0.55% |

## Largest Cash Months

| date | reported cash | book cash | gap | target | regime | action | reason | idle? | stocks / target |
|---|---:|---:|---:|---:|---|---|---|---:|---:|
| 2020-02-28 | 83.51% | 28.00% | 55.51% | 28.00% | risk_off_alert | rebalance | `cash_export_mismatch` | false | 18 / 18.0 |
| 2025-02-28 | 80.87% | 28.00% | 52.87% | 28.00% | risk_off_alert | partial_rebalance:core_compounder,early_scout | `cash_export_mismatch` | false | 18 / 18.0 |
| 2022-03-31 | 78.56% | 0.00% | 78.56% | 0.00% | growth_reentry_alert | partial_rebalance:core_compounder,early_scout | `cash_export_mismatch` | true | 18 / 18.0 |
| 2022-05-31 | 61.28% | 0.00% | 61.28% | 0.00% | balanced | circuit_breaker_rebalance | `cash_export_mismatch` | true | 27 / 18.0 |
| 2026-02-27 | 52.93% | 27.87% | 25.05% | 28.00% | risk_off_alert | partial_rebalance:core_compounder,early_scout | `mixed_confirmed_macro_and_idle_cash` | false | 30 / 18.0 |
| 2021-02-26 | 52.91% | 28.11% | 24.80% | 28.00% | risk_off_alert | rebalance | `mixed_confirmed_macro_and_idle_cash` | false | 25 / 18.0 |
| 2021-01-29 | 51.57% | 28.00% | 23.57% | 28.00% | risk_off_alert | partial_rebalance:core_compounder,early_scout | `mixed_confirmed_macro_and_idle_cash` | false | 17 / 18.0 |
| 2023-08-31 | 48.83% | 0.00% | 48.83% | 0.00% | balanced | partial_rebalance:core_compounder,early_scout | `cash_export_mismatch` | true | 18 / 18.0 |
| 2024-07-31 | 44.47% | 40.00% | 4.47% | 40.00% | systemic_alert | rebalance | `confirmed_macro_defense_cash` | false | 18 / 18.0 |
| 2024-03-28 | 44.43% | 0.00% | 44.43% | 0.00% | balanced | rebalance | `cash_export_mismatch` | true | 18 / 18.0 |
| 2021-12-31 | 43.26% | 0.00% | 43.26% | 0.00% | balanced | rebalance | `cash_export_mismatch` | true | 18 / 18.0 |
| 2023-09-29 | 42.53% | 40.00% | 2.53% | 40.00% | systemic_alert | rebalance | `confirmed_macro_defense_cash` | false | 17 / 18.0 |

## Largest Possible Idle-Cash Months

| date | reported cash | book cash | gap | target | regime | action | reason | stocks / target |
|---|---:|---:|---:|---:|---|---|---|---:|
| 2022-03-31 | 78.56% | 0.00% | 78.56% | 0.00% | growth_reentry_alert | partial_rebalance:core_compounder,early_scout | `cash_export_mismatch` | 18 / 18.0 |
| 2022-05-31 | 61.28% | 0.00% | 61.28% | 0.00% | balanced | circuit_breaker_rebalance | `cash_export_mismatch` | 27 / 18.0 |
| 2023-08-31 | 48.83% | 0.00% | 48.83% | 0.00% | balanced | partial_rebalance:core_compounder,early_scout | `cash_export_mismatch` | 18 / 18.0 |
| 2024-03-28 | 44.43% | 0.00% | 44.43% | 0.00% | balanced | rebalance | `cash_export_mismatch` | 18 / 18.0 |
| 2021-12-31 | 43.26% | 0.00% | 43.26% | 0.00% | balanced | rebalance | `cash_export_mismatch` | 18 / 18.0 |
| 2025-10-31 | 40.07% | 0.00% | 40.07% | 0.00% | balanced | partial_rebalance:core_compounder,early_scout | `cash_export_mismatch` | 26 / 18.0 |
| 2024-11-29 | 35.39% | 2.77% | 32.61% | 0.00% | growth_reentry_alert | rebalance | `cash_export_mismatch` | 43 / 18.0 |
| 2020-01-31 | 31.57% | 0.00% | 31.57% | 0.00% | balanced | partial_rebalance:core_compounder,early_scout | `cash_export_mismatch` | 18 / 18.0 |
| 2024-05-31 | 31.32% | 0.00% | 31.32% | 0.00% | balanced | rebalance | `cash_export_mismatch` | 29 / 18.0 |
| 2021-10-29 | 26.14% | 0.00% | 26.14% | 0.00% | growth_reentry_alert | rebalance | `cash_export_mismatch` | 24 / 18.0 |
| 2026-01-30 | 26.08% | 0.00% | 26.08% | 0.00% | balanced | rebalance | `cash_export_mismatch` | 18 / 18.0 |
| 2021-11-30 | 26.08% | 0.00% | 26.08% | 0.00% | balanced | partial_rebalance:core_compounder,early_scout | `cash_export_mismatch` | 18 / 18.0 |

## Interpretation

- Defense cash should be preserved in crisis/red regimes.
- Large defense cash should require confirmed macro deterioration, not a one-off event shock.
- Non-risk excess cash is the candidate pool for the next idle-cash redeploy A/B.
- If reported cash and explicit monthly-book cash diverge, downstream replays must use the reported cash source or the monthly book should be repaired.
