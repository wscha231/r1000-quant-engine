# Cash Policy Attribution

Research-only diagnostic. No production weights are changed.

## Summary

- months: 83
- avg reported cash: 5.03%
- avg period-end cash: 20.93%
- avg explicit CASH in monthly book: 5.03%
- avg reported-vs-book cash gap: 0.00%
- avg target defense cash: 4.82%
- avg excess cash over target: 0.21%
- months reported cash >20%: 13
- months reported cash >50%: 0
- months possible idle cash: 1
- months with cash export mismatch >2pp: 0

## Primary Reason Counts

| reason | months | cash-weight sum |
|---|---:|---:|
| `cap_limited_leftover` | 3 | 3.05% |
| `confirmed_macro_defense_cash` | 13 | 408.34% |
| `idle_cash_candidate` | 1 | 3.97% |
| `no_cash` | 65 | 0.22% |
| `partial_rebalance_leftover` | 1 | 1.53% |

## Largest Cash Months

| date | reported cash | book cash | gap | target | regime | action | reason | idle? | stocks / target |
|---|---:|---:|---:|---:|---|---|---|---:|---:|
| 2020-03-31 | 40.00% | 40.00% | 0.00% | 40.00% | systemic_alert | partial_rebalance:core_compounder,early_scout | `confirmed_macro_defense_cash` | false | 18 / 18.0 |
| 2023-09-29 | 40.00% | 40.00% | 0.00% | 40.00% | systemic_alert | partial_rebalance:core_compounder,early_scout | `confirmed_macro_defense_cash` | false | 17 / 18.0 |
| 2024-07-31 | 40.00% | 40.00% | 0.00% | 40.00% | systemic_alert | partial_rebalance:core_compounder,early_scout | `confirmed_macro_defense_cash` | false | 18 / 18.0 |
| 2022-04-29 | 33.43% | 33.43% | 0.00% | 28.00% | risk_off_alert | rebalance | `confirmed_macro_defense_cash` | false | 30 / 18.0 |
| 2021-02-26 | 30.13% | 30.13% | 0.00% | 28.00% | risk_off_alert | rebalance | `confirmed_macro_defense_cash` | false | 26 / 18.0 |
| 2026-02-27 | 28.89% | 28.89% | 0.00% | 28.00% | risk_off_alert | rebalance | `confirmed_macro_defense_cash` | false | 41 / 18.0 |
| 2019-05-31 | 28.00% | 28.00% | 0.00% | 28.00% | risk_off_alert | partial_rebalance:core_compounder,early_scout | `confirmed_macro_defense_cash` | false | 18 / 18.0 |
| 2020-02-28 | 28.00% | 28.00% | 0.00% | 28.00% | risk_off_alert | rebalance | `confirmed_macro_defense_cash` | false | 18 / 18.0 |
| 2020-10-30 | 28.00% | 28.00% | 0.00% | 28.00% | risk_off_alert | rebalance | `confirmed_macro_defense_cash` | false | 17 / 18.0 |
| 2021-09-30 | 28.00% | 28.00% | 0.00% | 28.00% | risk_off_alert | partial_rebalance:core_compounder,early_scout | `confirmed_macro_defense_cash` | false | 17 / 18.0 |
| 2025-03-31 | 28.00% | 28.00% | 0.00% | 28.00% | risk_off_alert | partial_rebalance:core_compounder,early_scout | `confirmed_macro_defense_cash` | false | 18 / 18.0 |
| 2021-01-29 | 28.00% | 28.00% | 0.00% | 28.00% | risk_off_alert | partial_rebalance:core_compounder,early_scout | `confirmed_macro_defense_cash` | false | 17 / 18.0 |

## Largest Possible Idle-Cash Months

| date | reported cash | book cash | gap | target | regime | action | reason | stocks / target |
|---|---:|---:|---:|---:|---|---|---|---:|

## Interpretation

- Defense cash should be preserved in crisis/red regimes.
- Large defense cash should require confirmed macro deterioration, not a one-off event shock.
- Non-risk excess cash is the candidate pool for the next idle-cash redeploy A/B.
- If reported cash and explicit monthly-book cash diverge, downstream replays must use the reported cash source or the monthly book should be repaired.
