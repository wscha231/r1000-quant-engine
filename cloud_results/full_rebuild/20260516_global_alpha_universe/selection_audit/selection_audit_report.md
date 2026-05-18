# Selection Audit

Research-only diagnostic. It does not change production weights.

## Summary

- latest candidate rows: 553
- current main names: 17
- current concentrated names: 7
- selected stale review count: 2
- omitted monster candidates in top list: 2

## Decision Buckets

- `not_selected_low_priority`: 109
- `omitted_candidate_gate_block`: 423
- `omitted_monster_candidate`: 2
- `omitted_stale_leader`: 6
- `selected_concentrated`: 3
- `selected_main`: 8
- `selected_main_stale_review`: 2

## Current Selected

| ticker | bucket | main | concentrated | pressure | months main / conc |
|---|---|---:|---:|---:|---:|
| PR | `selected_main` | 4.0% | 0.0% | 0.661 | 3 / 5 |
| FTI | `selected_main` | 3.7% | 0.0% | 0.648 | 1 / 0 |
| GEV | `selected_main` | 8.9% | 0.0% | 0.625 | 3 / 0 |
| GOOG | `selected_main_stale_review` | 14.0% | 0.0% | 0.568 | 41 / 16 |
| AMZN | `selected_main` | 7.8% | 0.0% | 0.497 | 24 / 3 |
| CBOE | `selected_main` | 2.9% | 0.0% | 0.496 | 5 / 2 |
| PWR | `selected_main` | 3.2% | 0.0% | 0.485 | 10 / 0 |
| PLTR | `selected_main_stale_review` | 5.2% | 0.0% | 0.415 | 14 / 0 |
| MLI | `selected_main` | 4.0% | 0.0% | 0.401 | 4 / 6 |
| APP | `selected_main` | 10.5% | 0.0% | 0.271 | 6 / 1 |
| EXPE | `selected_concentrated` | 0.0% | 20.9% | 0.572 | 8 / 9 |
| ADI | `selected_concentrated` | 0.0% | 23.4% | 0.556 | 4 / 0 |
| JHG | `selected_concentrated` | 0.0% | 20.7% | 0.531 | 0 / 0 |

## Top Omitted Candidates

| ticker | bucket | pressure | score | conc score | monster | risk block | gate |
|---|---|---:|---:|---:|---:|---:|---|
| LNG | `not_selected_low_priority` | 0.668 | 5.645 | 0.000 | 0.544 | 0.122 | future_relaxed |
| ETR | `not_selected_low_priority` | 0.658 | 2.930 | 0.000 | 0.583 | 0.000 | early_relaxed |
| SU | `omitted_monster_candidate` | 0.655 | 2.548 | 0.000 | 0.622 | 0.108 | adr_global_alpha_fallback |
| CNQ | `not_selected_low_priority` | 0.655 | 2.656 | 0.000 | 0.598 | 0.108 | adr_global_alpha_fallback |
| OKE | `omitted_candidate_gate_block` | 0.653 | 2.699 | 0.000 | 0.561 | 0.014 | rejected |
| SLB | `not_selected_low_priority` | 0.651 | 2.722 | 0.000 | 0.589 | 0.108 | future_relaxed |
| ROST | `not_selected_low_priority` | 0.650 | 3.342 | 0.000 | 0.534 | 0.242 | future_relaxed |
| DAL | `omitted_candidate_gate_block` | 0.648 | 3.005 | 0.000 | 0.488 | 0.147 | rejected |
| VZ | `not_selected_low_priority` | 0.647 | 4.491 | 0.000 | 0.515 | 0.000 | core_strict |
| TRGP | `omitted_monster_candidate` | 0.646 | 2.088 | 0.000 | 0.629 | 0.108 | future_relaxed |
| MTDR | `not_selected_low_priority` | 0.628 | 1.810 | 0.000 | 0.529 | 0.339 | early_relaxed |
| ATO | `not_selected_low_priority` | 0.626 | 2.097 | 0.000 | 0.518 | 0.000 | future_relaxed |
| PBR | `not_selected_low_priority` | 0.624 | 2.018 | 0.000 | 0.524 | 0.108 | adr_global_alpha_fallback |
| USFD | `omitted_candidate_gate_block` | 0.624 | 2.464 | 0.000 | 0.469 | 0.000 | rejected |
| ED | `omitted_candidate_gate_block` | 0.620 | 2.188 | 0.000 | 0.513 | 0.000 | rejected |
| DUK | `not_selected_low_priority` | 0.613 | 3.150 | 0.000 | 0.494 | 0.000 | future_relaxed |
| CVX | `omitted_candidate_gate_block` | 0.610 | 4.437 | 0.000 | 0.509 | 0.108 | rejected |
| FANG | `not_selected_low_priority` | 0.607 | 2.401 | 0.000 | 0.596 | 0.108 | future_relaxed |
| EQIX | `omitted_candidate_gate_block` | 0.601 | 2.719 | 0.000 | 0.482 | 0.000 | rejected |
| UTHR | `not_selected_low_priority` | 0.601 | 1.144 | 0.000 | 0.569 | 0.242 | future_relaxed |

## Interpretation

- Use `current_selected_audit.csv` to explain why current holdings were selected and whether any are stale-review names.
- Use `omitted_high_potential_candidates.csv` to inspect high-pressure candidates that were excluded by gates, risk blocks, caps, or lower priority.
- Use `historical_hold_persistence.csv` to distinguish long-held winners from newly selected names.
- This audit is intentionally explanatory only; it must not be used as a promotion gate without historical replay.
