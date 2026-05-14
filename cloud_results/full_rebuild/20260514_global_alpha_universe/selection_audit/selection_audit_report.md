# Selection Audit

Research-only diagnostic. It does not change production weights.

## Summary

- latest candidate rows: 608
- current main names: 17
- current concentrated names: 3
- selected stale review count: 2
- omitted monster candidates in top list: 0

## Decision Buckets

- `not_selected_low_priority`: 124
- `omitted_candidate_gate_block`: 459
- `omitted_risk_entry_block`: 1
- `omitted_stale_leader`: 11
- `selected_both`: 1
- `selected_concentrated`: 2
- `selected_main`: 8
- `selected_main_stale_review`: 2

## Current Selected

| ticker | bucket | main | concentrated | pressure | months main / conc |
|---|---|---:|---:|---:|---:|
| MRVL | `selected_both` | 6.2% | 50.0% | 0.642 | 0 / 0 |
| PR | `selected_main` | 4.0% | 0.0% | 0.664 | 4 / 5 |
| VRT | `selected_main` | 6.2% | 0.0% | 0.636 | 13 / 3 |
| WDC | `selected_main` | 5.8% | 0.0% | 0.634 | 3 / 6 |
| FTI | `selected_main` | 5.5% | 0.0% | 0.630 | 1 / 0 |
| GEV | `selected_main` | 12.0% | 0.0% | 0.626 | 2 / 0 |
| LRCX | `selected_main_stale_review` | 6.2% | 0.0% | 0.623 | 44 / 42 |
| GOOG | `selected_main_stale_review` | 12.0% | 0.0% | 0.572 | 19 / 11 |
| CBOE | `selected_main` | 5.5% | 0.0% | 0.484 | 6 / 3 |
| HPE | `selected_main` | 4.0% | 0.0% | 0.471 | 0 / 0 |
| MLI | `selected_main` | 4.0% | 0.0% | 0.391 | 10 / 2 |
| CIEN | `selected_concentrated` | 0.0% | 25.0% | 0.657 | 0 / 4 |
| MU | `selected_concentrated` | 0.0% | 25.0% | 0.587 | 9 / 8 |

## Top Omitted Candidates

| ticker | bucket | pressure | score | conc score | monster | risk block | gate |
|---|---|---:|---:|---:|---:|---:|---|
| LNG | `not_selected_low_priority` | 0.667 | 5.584 | 0.000 | 0.540 | 0.122 | future_relaxed |
| VZ | `not_selected_low_priority` | 0.659 | 4.346 | 0.000 | 0.595 | 0.000 | future_relaxed |
| ETR | `not_selected_low_priority` | 0.656 | 3.442 | 0.000 | 0.575 | 0.000 | early_relaxed |
| CNQ | `not_selected_low_priority` | 0.649 | 2.771 | 0.000 | 0.587 | 0.108 | adr_global_alpha_fallback |
| SLB | `not_selected_low_priority` | 0.648 | 3.068 | 0.000 | 0.583 | 0.108 | future_relaxed |
| SU | `not_selected_low_priority` | 0.646 | 2.605 | 0.000 | 0.610 | 0.108 | adr_global_alpha_fallback |
| SNDK | `omitted_candidate_gate_block` | 0.645 | 3.727 | 0.000 | 0.478 | 0.333 | rejected |
| DAL | `omitted_candidate_gate_block` | 0.641 | 3.492 | 0.000 | 0.479 | 0.147 | rejected |
| TRGP | `not_selected_low_priority` | 0.639 | 2.118 | 0.000 | 0.617 | 0.108 | future_relaxed |
| OKE | `omitted_candidate_gate_block` | 0.638 | 2.544 | 0.000 | 0.548 | 0.014 | rejected |
| LITE | `not_selected_low_priority` | 0.636 | 3.282 | 0.000 | 0.526 | 0.333 | future_relaxed |
| ROST | `not_selected_low_priority` | 0.630 | 2.952 | 0.000 | 0.520 | 0.242 | future_relaxed |
| MTDR | `not_selected_low_priority` | 0.625 | 2.037 | 0.000 | 0.521 | 0.339 | early_relaxed |
| AMAT | `omitted_stale_leader` | 0.625 | 4.978 | 0.000 | 0.401 | 0.255 | core_strict |
| ATO | `not_selected_low_priority` | 0.618 | 2.354 | 0.000 | 0.515 | 0.000 | future_relaxed |
| JBL | `not_selected_low_priority` | 0.616 | 1.945 | 0.000 | 0.528 | 0.133 | future_relaxed |
| PBR | `not_selected_low_priority` | 0.614 | 1.998 | 0.000 | 0.520 | 0.108 | adr_global_alpha_fallback |
| UTHR | `not_selected_low_priority` | 0.614 | 1.685 | 0.000 | 0.555 | 0.242 | future_relaxed |
| NXT | `not_selected_low_priority` | 0.611 | 1.680 | 0.000 | 0.517 | 0.458 | future_relaxed |
| CVX | `omitted_candidate_gate_block` | 0.611 | 4.956 | 0.000 | 0.509 | 0.108 | rejected |

## Interpretation

- Use `current_selected_audit.csv` to explain why current holdings were selected and whether any are stale-review names.
- Use `omitted_high_potential_candidates.csv` to inspect high-pressure candidates that were excluded by gates, risk blocks, caps, or lower priority.
- Use `historical_hold_persistence.csv` to distinguish long-held winners from newly selected names.
- This audit is intentionally explanatory only; it must not be used as a promotion gate without historical replay.
