# Selection Audit

Research-only diagnostic. It does not change production weights.

## Summary

- latest candidate rows: 608
- current main names: 18
- current concentrated names: 4
- selected stale review count: 2
- omitted monster candidates in top list: 0

## Decision Buckets

- `not_selected_low_priority`: 126
- `omitted_candidate_gate_block`: 458
- `omitted_risk_entry_block`: 1
- `omitted_stale_leader`: 11
- `selected_both`: 2
- `selected_concentrated`: 1
- `selected_main`: 7
- `selected_main_stale_review`: 2

## Current Selected

| ticker | bucket | main | concentrated | pressure | months main / conc |
|---|---|---:|---:|---:|---:|
| MRVL | `selected_both` | 5.7% | 19.8% | 0.641 | 0 / 0 |
| WDC | `selected_both` | 5.3% | 27.6% | 0.633 | 3 / 5 |
| PR | `selected_main` | 4.0% | 0.0% | 0.667 | 4 / 4 |
| VRT | `selected_main` | 5.7% | 0.0% | 0.638 | 11 / 0 |
| FTI | `selected_main` | 4.9% | 0.0% | 0.635 | 1 / 0 |
| GEV | `selected_main` | 11.9% | 0.0% | 0.625 | 2 / 3 |
| AMD | `selected_main_stale_review` | 5.7% | 0.0% | 0.595 | 11 / 2 |
| GOOG | `selected_main_stale_review` | 14.0% | 0.0% | 0.574 | 17 / 11 |
| CBOE | `selected_main` | 4.8% | 0.0% | 0.488 | 6 / 3 |
| HPE | `selected_main` | 4.0% | 0.0% | 0.461 | 0 / 1 |
| MLI | `selected_main` | 4.0% | 0.0% | 0.389 | 6 / 2 |
| MU | `selected_concentrated` | 0.0% | 14.3% | 0.589 | 8 / 10 |

## Top Omitted Candidates

| ticker | bucket | pressure | score | conc score | monster | risk block | gate |
|---|---|---:|---:|---:|---:|---:|---|
| LNG | `not_selected_low_priority` | 0.666 | 5.945 | 0.000 | 0.539 | 0.122 | future_relaxed |
| VZ | `not_selected_low_priority` | 0.659 | 4.358 | 0.000 | 0.595 | 0.000 | future_relaxed |
| ETR | `not_selected_low_priority` | 0.658 | 3.557 | 0.000 | 0.576 | 0.000 | early_relaxed |
| CIEN | `not_selected_low_priority` | 0.653 | 3.186 | 0.000 | 0.559 | 0.333 | future_relaxed |
| SU | `not_selected_low_priority` | 0.651 | 2.879 | 0.000 | 0.611 | 0.108 | adr_global_alpha_fallback |
| SLB | `not_selected_low_priority` | 0.651 | 3.411 | 0.000 | 0.583 | 0.108 | future_relaxed |
| CNQ | `not_selected_low_priority` | 0.648 | 2.912 | 0.000 | 0.586 | 0.108 | adr_global_alpha_fallback |
| SNDK | `omitted_candidate_gate_block` | 0.648 | 3.963 | 0.000 | 0.479 | 0.333 | rejected |
| OKE | `omitted_candidate_gate_block` | 0.644 | 2.876 | 0.000 | 0.548 | 0.014 | rejected |
| DAL | `omitted_candidate_gate_block` | 0.639 | 3.437 | 0.000 | 0.478 | 0.147 | rejected |
| TRGP | `not_selected_low_priority` | 0.639 | 2.098 | 0.000 | 0.617 | 0.108 | future_relaxed |
| MTDR | `not_selected_low_priority` | 0.633 | 2.359 | 0.000 | 0.521 | 0.339 | early_relaxed |
| ROST | `not_selected_low_priority` | 0.632 | 3.061 | 0.000 | 0.520 | 0.242 | future_relaxed |
| AMAT | `omitted_stale_leader` | 0.624 | 4.866 | 0.000 | 0.401 | 0.255 | core_strict |
| PBR | `not_selected_low_priority` | 0.620 | 2.249 | 0.000 | 0.519 | 0.108 | adr_global_alpha_fallback |
| LRCX | `omitted_stale_leader` | 0.619 | 4.788 | 0.000 | 0.395 | 0.347 | core_strict |
| LITE | `not_selected_low_priority` | 0.619 | 2.265 | 0.000 | 0.526 | 0.333 | future_relaxed |
| ATO | `not_selected_low_priority` | 0.619 | 2.317 | 0.000 | 0.516 | 0.000 | future_relaxed |
| JBL | `not_selected_low_priority` | 0.616 | 1.923 | 0.000 | 0.528 | 0.133 | future_relaxed |
| NXT | `not_selected_low_priority` | 0.613 | 1.764 | 0.000 | 0.516 | 0.458 | future_relaxed |

## Interpretation

- Use `current_selected_audit.csv` to explain why current holdings were selected and whether any are stale-review names.
- Use `omitted_high_potential_candidates.csv` to inspect high-pressure candidates that were excluded by gates, risk blocks, caps, or lower priority.
- Use `historical_hold_persistence.csv` to distinguish long-held winners from newly selected names.
- This audit is intentionally explanatory only; it must not be used as a promotion gate without historical replay.
