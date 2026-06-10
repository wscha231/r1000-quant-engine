# Selection Audit

Research-only diagnostic. It does not change production weights.

## Summary

- latest candidate rows: 606
- current main names: 18
- current concentrated names: 5
- selected stale review count: 2
- omitted monster candidates in top list: 0

## Decision Buckets

- `not_selected_low_priority`: 125
- `omitted_candidate_gate_block`: 454
- `omitted_risk_entry_block`: 1
- `omitted_stale_leader`: 12
- `selected_both`: 1
- `selected_concentrated`: 2
- `selected_main`: 9
- `selected_main_stale_review`: 2

## Current Selected

| ticker | bucket | main | concentrated | pressure | months main / conc |
|---|---|---:|---:|---:|---:|
| AKAM | `selected_both` | 4.0% | 24.2% | 0.561 | 0 / 0 |
| PR | `selected_main` | 4.0% | 0.0% | 0.659 | 3 / 7 |
| MRVL | `selected_main` | 6.4% | 0.0% | 0.632 | 0 / 0 |
| VRT | `selected_main` | 6.4% | 0.0% | 0.630 | 11 / 0 |
| SU | `selected_main` | 4.0% | 0.0% | 0.630 | 0 / 0 |
| GEV | `selected_main` | 15.2% | 0.0% | 0.622 | 1 / 0 |
| LRCX | `selected_main_stale_review` | 5.6% | 0.0% | 0.617 | 37 / 39 |
| FTI | `selected_main` | 4.2% | 0.0% | 0.616 | 1 / 0 |
| GOOG | `selected_main_stale_review` | 11.3% | 0.0% | 0.571 | 20 / 13 |
| CBOE | `selected_main` | 4.0% | 0.0% | 0.470 | 3 / 4 |
| PWR | `selected_main` | 4.2% | 0.0% | 0.421 | 6 / 0 |
| MLI | `selected_main` | 4.0% | 0.0% | 0.398 | 3 / 2 |
| SNDK | `selected_concentrated` | 0.0% | 10.8% | 0.642 | 0 / 0 |
| WDC | `selected_concentrated` | 0.0% | 19.4% | 0.629 | 3 / 5 |

## Top Omitted Candidates

| ticker | bucket | pressure | score | conc score | monster | risk block | gate |
|---|---|---:|---:|---:|---:|---:|---|
| LNG | `not_selected_low_priority` | 0.664 | 4.739 | 0.000 | 0.541 | 0.122 | future_relaxed |
| VZ | `not_selected_low_priority` | 0.660 | 4.111 | 0.000 | 0.595 | 0.000 | future_relaxed |
| ETR | `not_selected_low_priority` | 0.657 | 3.258 | 0.000 | 0.577 | 0.000 | early_relaxed |
| SLB | `not_selected_low_priority` | 0.649 | 3.061 | 0.000 | 0.581 | 0.108 | future_relaxed |
| OKE | `omitted_candidate_gate_block` | 0.641 | 2.570 | 0.000 | 0.548 | 0.014 | rejected |
| CNQ | `not_selected_low_priority` | 0.637 | 2.263 | 0.000 | 0.586 | 0.108 | adr_global_alpha_fallback |
| DAL | `omitted_candidate_gate_block` | 0.637 | 3.070 | 0.000 | 0.478 | 0.147 | rejected |
| CIEN | `not_selected_low_priority` | 0.628 | 1.940 | 0.000 | 0.560 | 0.333 | future_relaxed |
| ATO | `not_selected_low_priority` | 0.622 | 2.361 | 0.000 | 0.518 | 0.000 | future_relaxed |
| ROST | `not_selected_low_priority` | 0.621 | 2.361 | 0.000 | 0.522 | 0.242 | future_relaxed |
| AMAT | `omitted_stale_leader` | 0.619 | 4.382 | 0.000 | 0.394 | 0.255 | core_strict |
| TRGP | `not_selected_low_priority` | 0.614 | 1.509 | 0.000 | 0.618 | 0.108 | future_relaxed |
| ED | `omitted_candidate_gate_block` | 0.610 | 2.264 | 0.000 | 0.507 | 0.000 | rejected |
| DUK | `not_selected_low_priority` | 0.609 | 3.404 | 0.000 | 0.494 | 0.000 | future_relaxed |
| CVX | `omitted_candidate_gate_block` | 0.609 | 4.690 | 0.000 | 0.506 | 0.108 | rejected |
| ENB | `not_selected_low_priority` | 0.604 | 2.917 | 0.000 | 0.586 | 0.000 | adr_global_alpha_fallback |
| FANG | `not_selected_low_priority` | 0.603 | 2.557 | 0.000 | 0.590 | 0.108 | future_relaxed |
| DTM | `not_selected_low_priority` | 0.599 | 1.537 | 0.000 | 0.540 | 0.133 | future_relaxed |
| NXT | `not_selected_low_priority` | 0.598 | 1.286 | 0.000 | 0.531 | 0.458 | future_relaxed |
| MTDR | `not_selected_low_priority` | 0.596 | 1.314 | 0.000 | 0.522 | 0.339 | early_relaxed |

## Interpretation

- Use `current_selected_audit.csv` to explain why current holdings were selected and whether any are stale-review names.
- Use `omitted_high_potential_candidates.csv` to inspect high-pressure candidates that were excluded by gates, risk blocks, caps, or lower priority.
- Use `historical_hold_persistence.csv` to distinguish long-held winners from newly selected names.
- This audit is intentionally explanatory only; it must not be used as a promotion gate without historical replay.
