# Cash Policy Attribution

Research-only diagnostic. No production weights are changed.

## Summary

- months: 83
- avg reported cash: 4.97%
- avg period-end cash: 21.99%
- avg explicit CASH in monthly book: 4.97%
- avg reported-vs-book cash gap: 0.00%
- avg target defense cash: 4.78%
- avg excess cash over target: 0.18%
- months reported cash >20%: 13
- months reported cash >50%: 0
- months possible idle cash: 2
- months with cash export mismatch >2pp: 0

## Primary Reason Counts

| reason | months | cash-weight sum |
|---|---:|---:|
| `cap_limited_leftover` | 1 | 1.46% |
| `confirmed_macro_defense_cash` | 13 | 402.91% |
| `no_cash` | 66 | 0.70% |
| `partial_rebalance_leftover` | 3 | 7.05% |

## Largest Cash Months

| date | reported cash | book cash | gap | target | regime | action | reason | idle? | stocks / target |
|---|---:|---:|---:|---:|---|---|---|---:|---:|
| 2020-03-31 | 40.00% | 40.00% | 0.00% | 40.00% | systemic_alert | partial_rebalance:core_compounder,early_scout | `confirmed_macro_defense_cash` | false | 18 / 18.0 |
| 2023-09-29 | 40.00% | 40.00% | 0.00% | 40.00% | systemic_alert | partial_rebalance:core_compounder,early_scout | `confirmed_macro_defense_cash` | false | 18 / 18.0 |
| 2024-07-31 | 39.37% | 39.37% | 0.00% | 40.00% | systemic_alert | partial_rebalance:core_compounder,early_scout | `confirmed_macro_defense_cash` | false | 27 / 18.0 |
| 2022-04-29 | 34.06% | 34.06% | 0.00% | 28.00% | risk_off_alert | rebalance | `confirmed_macro_defense_cash` | false | 31 / 18.0 |
| 2019-05-31 | 28.00% | 28.00% | 0.00% | 28.00% | risk_off_alert | partial_rebalance:core_compounder,early_scout | `confirmed_macro_defense_cash` | false | 18 / 18.0 |
| 2020-02-28 | 28.00% | 28.00% | 0.00% | 28.00% | risk_off_alert | rebalance | `confirmed_macro_defense_cash` | false | 18 / 18.0 |
| 2020-10-30 | 28.00% | 28.00% | 0.00% | 28.00% | risk_off_alert | rebalance | `confirmed_macro_defense_cash` | false | 17 / 18.0 |
| 2021-01-29 | 28.00% | 28.00% | 0.00% | 28.00% | risk_off_alert | partial_rebalance:core_compounder,early_scout | `confirmed_macro_defense_cash` | false | 17 / 18.0 |
| 2021-02-26 | 28.00% | 28.00% | 0.00% | 28.00% | risk_off_alert | rebalance | `confirmed_macro_defense_cash` | false | 17 / 18.0 |
| 2021-09-30 | 28.00% | 28.00% | 0.00% | 28.00% | risk_off_alert | partial_rebalance:core_compounder,early_scout | `confirmed_macro_defense_cash` | false | 17 / 18.0 |
| 2025-03-31 | 28.00% | 28.00% | 0.00% | 28.00% | risk_off_alert | partial_rebalance:core_compounder,early_scout | `confirmed_macro_defense_cash` | false | 18 / 18.0 |
| 2026-02-27 | 28.00% | 28.00% | 0.00% | 28.00% | risk_off_alert | rebalance | `confirmed_macro_defense_cash` | false | 18 / 18.0 |

## Largest Possible Idle-Cash Months

| date | reported cash | book cash | gap | target | regime | action | reason | stocks / target |
|---|---:|---:|---:|---:|---|---|---|---:|

## Interpretation

- Defense cash should be preserved in crisis/red regimes.
- Large defense cash should require confirmed macro deterioration, not a one-off event shock.
- Non-risk excess cash is the candidate pool for the next idle-cash redeploy A/B.
- If reported cash and explicit monthly-book cash diverge, downstream replays must use the reported cash source or the monthly book should be repaired.
