# Cash Policy Attribution

Research-only diagnostic. No production weights are changed.

## Summary

- months: 106
- avg reported cash: 19.37%
- avg explicit CASH in monthly book: 3.65%
- avg reported-vs-book cash gap: 15.73%
- avg target defense cash: 3.45%
- avg excess cash over target: 15.92%
- months reported cash >20%: 34
- months reported cash >50%: 10
- months possible idle cash: 82
- months with cash export mismatch >2pp: 96

## Primary Reason Counts

| reason | months | cash-weight sum |
|---|---:|---:|
| `cash_export_mismatch` | 89 | 1761.80% |
| `confirmed_macro_defense_cash` | 8 | 281.77% |
| `idle_cash_candidate` | 1 | 6.12% |
| `no_cash` | 6 | 0.00% |
| `partial_rebalance_leftover` | 2 | 3.91% |

## Largest Cash Months

| date | reported cash | book cash | gap | target | regime | action | reason | idle? | stocks / target |
|---|---:|---:|---:|---:|---|---|---|---:|---:|
| 2020-02-28 | 83.94% | 28.00% | 55.94% | 28.00% | risk_off_alert | partial_rebalance:core_compounder,early_scout | `cash_export_mismatch` | false | 18 / 18.0 |
| 2018-11-30 | 78.32% | 0.00% | 78.32% | 0.00% | balanced | rebalance | `cash_export_mismatch` | true | 27 / 18.0 |
| 2026-02-27 | 72.68% | 28.23% | 44.44% | 28.00% | risk_off_alert | partial_rebalance:core_compounder,early_scout | `cash_export_mismatch` | false | 34 / 18.0 |
| 2022-03-31 | 71.54% | 0.00% | 71.54% | 0.00% | growth_reentry_alert | circuit_breaker_release | `cash_export_mismatch` | true | 18 / 18.0 |
| 2025-02-28 | 68.14% | 23.65% | 44.49% | 28.00% | risk_off_alert | partial_rebalance:core_compounder,early_scout | `cash_export_mismatch` | false | 45 / 18.0 |
| 2023-08-31 | 59.88% | 0.00% | 59.88% | 0.00% | balanced | partial_rebalance:core_compounder,early_scout | `cash_export_mismatch` | true | 18 / 18.0 |
| 2021-02-26 | 59.81% | 28.00% | 31.81% | 28.00% | risk_off_alert | partial_rebalance:core_compounder,early_scout | `cash_export_mismatch` | false | 17 / 18.0 |
| 2018-09-28 | 58.95% | 0.00% | 58.95% | 0.00% | balanced | rebalance | `cash_export_mismatch` | true | 18 / 18.0 |
| 2022-05-31 | 55.44% | 0.00% | 55.44% | 0.00% | balanced | circuit_breaker_rebalance | `cash_export_mismatch` | false | 27 / 18.0 |
| 2025-10-31 | 53.87% | 0.00% | 53.87% | 0.00% | balanced | partial_rebalance:core_compounder,early_scout | `cash_export_mismatch` | true | 25 / 18.0 |
| 2021-12-31 | 48.09% | 0.00% | 48.09% | 0.00% | balanced | partial_rebalance:core_compounder,early_scout | `cash_export_mismatch` | true | 17 / 18.0 |
| 2021-08-31 | 46.10% | 0.00% | 46.10% | 0.00% | balanced | partial_rebalance:core_compounder,early_scout | `cash_export_mismatch` | true | 40 / 18.0 |

## Largest Possible Idle-Cash Months

| date | reported cash | book cash | gap | target | regime | action | reason | stocks / target |
|---|---:|---:|---:|---:|---|---|---|---:|
| 2018-11-30 | 78.32% | 0.00% | 78.32% | 0.00% | balanced | rebalance | `cash_export_mismatch` | 27 / 18.0 |
| 2022-03-31 | 71.54% | 0.00% | 71.54% | 0.00% | growth_reentry_alert | circuit_breaker_release | `cash_export_mismatch` | 18 / 18.0 |
| 2023-08-31 | 59.88% | 0.00% | 59.88% | 0.00% | balanced | partial_rebalance:core_compounder,early_scout | `cash_export_mismatch` | 18 / 18.0 |
| 2018-09-28 | 58.95% | 0.00% | 58.95% | 0.00% | balanced | rebalance | `cash_export_mismatch` | 18 / 18.0 |
| 2025-10-31 | 53.87% | 0.00% | 53.87% | 0.00% | balanced | partial_rebalance:core_compounder,early_scout | `cash_export_mismatch` | 25 / 18.0 |
| 2021-12-31 | 48.09% | 0.00% | 48.09% | 0.00% | balanced | partial_rebalance:core_compounder,early_scout | `cash_export_mismatch` | 17 / 18.0 |
| 2021-08-31 | 46.10% | 0.00% | 46.10% | 0.00% | balanced | partial_rebalance:core_compounder,early_scout | `cash_export_mismatch` | 40 / 18.0 |
| 2025-06-30 | 36.52% | 0.00% | 36.52% | 0.00% | balanced | partial_rebalance:core_compounder,early_scout | `cash_export_mismatch` | 18 / 18.0 |
| 2026-01-30 | 32.64% | 0.00% | 32.64% | 0.00% | balanced | rebalance | `cash_export_mismatch` | 26 / 18.0 |
| 2024-03-28 | 31.88% | 0.07% | 31.81% | 0.00% | balanced | rebalance | `cash_export_mismatch` | 18 / 18.0 |
| 2024-11-29 | 31.60% | 0.00% | 31.60% | 0.00% | growth_reentry_alert | rebalance | `cash_export_mismatch` | 49 / 18.0 |
| 2020-08-31 | 30.10% | 0.00% | 30.10% | 0.00% | balanced | partial_rebalance:core_compounder,early_scout | `cash_export_mismatch` | 17 / 18.0 |

## Interpretation

- Defense cash should be preserved in crisis/red regimes.
- Large defense cash should require confirmed macro deterioration, not a one-off event shock.
- Non-risk excess cash is the candidate pool for the next idle-cash redeploy A/B.
- If reported cash and explicit monthly-book cash diverge, downstream replays must use the reported cash source or the monthly book should be repaired.
