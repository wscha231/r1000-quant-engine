# Selection Audit

Research-only diagnostic. It does not change production weights.

## Summary

- latest candidate rows: 604
- current main names: 17
- current concentrated names: 4
- selected stale review count: 2
- omitted monster candidates in top list: 0

## Decision Buckets

- `not_selected_low_priority`: 124
- `omitted_candidate_gate_block`: 454
- `omitted_risk_entry_block`: 1
- `omitted_stale_leader`: 11
- `selected_concentrated`: 3
- `selected_main`: 9
- `selected_main_stale_review`: 2

## Current Selected

| ticker | bucket | main | concentrated | pressure | months main / conc |
|---|---|---:|---:|---:|---:|
| PR | `selected_main` | 4.0% | 0.0% | 0.651 | 6 / 7 |
| VRT | `selected_main` | 6.9% | 0.0% | 0.630 | 12 / 0 |
| GEV | `selected_main` | 12.0% | 0.0% | 0.621 | 2 / 0 |
| LRCX | `selected_main_stale_review` | 5.2% | 0.0% | 0.616 | 43 / 40 |
| FTI | `selected_main` | 6.8% | 0.0% | 0.599 | 1 / 0 |
| GOOGL | `selected_main_stale_review` | 12.0% | 0.0% | 0.577 | 34 / 14 |
| AKAM | `selected_main` | 3.6% | 0.0% | 0.565 | 1 / 0 |
| HPE | `selected_main` | 3.6% | 0.0% | 0.471 | 0 / 0 |
| PWR | `selected_main` | 6.8% | 0.0% | 0.413 | 2 / 0 |
| MLI | `selected_main` | 4.0% | 0.0% | 0.412 | 8 / 2 |
| ENTG | `selected_main` | 3.6% | 0.0% | 0.288 | 0 / 0 |
| SNDK | `selected_concentrated` | 0.0% | 15.2% | 0.651 | 0 / 0 |
| WDC | `selected_concentrated` | 0.0% | 26.1% | 0.630 | 2 / 5 |
| MU | `selected_concentrated` | 0.0% | 26.5% | 0.589 | 10 / 5 |

## Top Omitted Candidates

| ticker | bucket | pressure | score | conc score | monster | risk block | gate |
|---|---|---:|---:|---:|---:|---:|---|
| LNG | `not_selected_low_priority` | 0.666 | 5.002 | 0.000 | 0.541 | 0.122 | future_relaxed |
| VZ | `not_selected_low_priority` | 0.660 | 4.155 | 0.000 | 0.595 | 0.000 | future_relaxed |
| ETR | `not_selected_low_priority` | 0.657 | 3.486 | 0.000 | 0.577 | 0.000 | early_relaxed |
| SLB | `not_selected_low_priority` | 0.641 | 2.680 | 0.000 | 0.581 | 0.108 | future_relaxed |
| OKE | `omitted_candidate_gate_block` | 0.641 | 2.487 | 0.000 | 0.548 | 0.014 | rejected |
| CNQ | `not_selected_low_priority` | 0.637 | 2.184 | 0.000 | 0.586 | 0.108 | adr_global_alpha_fallback |
| MRVL | `omitted_candidate_gate_block` | 0.636 | 3.319 | 0.000 | 0.551 | 0.133 | rejected |
| SU | `not_selected_low_priority` | 0.631 | 1.868 | 0.000 | 0.612 | 0.108 | adr_global_alpha_fallback |
| DAL | `omitted_candidate_gate_block` | 0.630 | 2.705 | 0.000 | 0.478 | 0.147 | rejected |
| CIEN | `not_selected_low_priority` | 0.630 | 1.953 | 0.000 | 0.560 | 0.333 | future_relaxed |
| TRGP | `not_selected_low_priority` | 0.624 | 1.728 | 0.000 | 0.617 | 0.108 | future_relaxed |
| ATO | `not_selected_low_priority` | 0.623 | 2.398 | 0.000 | 0.518 | 0.000 | future_relaxed |
| ROST | `not_selected_low_priority` | 0.618 | 2.200 | 0.000 | 0.522 | 0.242 | future_relaxed |
| AMAT | `omitted_stale_leader` | 0.616 | 3.949 | 0.000 | 0.394 | 0.255 | core_strict |
| CVX | `omitted_candidate_gate_block` | 0.608 | 4.534 | 0.000 | 0.506 | 0.108 | rejected |
| ED | `omitted_candidate_gate_block` | 0.608 | 2.134 | 0.000 | 0.507 | 0.000 | rejected |
| DUK | `not_selected_low_priority` | 0.607 | 3.280 | 0.000 | 0.494 | 0.000 | future_relaxed |
| DTM | `not_selected_low_priority` | 0.605 | 1.618 | 0.000 | 0.541 | 0.133 | future_relaxed |
| ENB | `not_selected_low_priority` | 0.604 | 2.787 | 0.000 | 0.586 | 0.000 | adr_global_alpha_fallback |
| LITE | `not_selected_low_priority` | 0.603 | 1.777 | 0.000 | 0.523 | 0.333 | future_relaxed |

## Interpretation

- Use `current_selected_audit.csv` to explain why current holdings were selected and whether any are stale-review names.
- Use `omitted_high_potential_candidates.csv` to inspect high-pressure candidates that were excluded by gates, risk blocks, caps, or lower priority.
- Use `historical_hold_persistence.csv` to distinguish long-held winners from newly selected names.
- This audit is intentionally explanatory only; it must not be used as a promotion gate without historical replay.
