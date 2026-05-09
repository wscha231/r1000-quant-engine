# Selection Audit

Research-only diagnostic. It does not change production weights.

## Summary

- latest candidate rows: 606
- current main names: 18
- current concentrated names: 3
- selected stale review count: 1
- omitted monster candidates in top list: 0

## Decision Buckets

- `not_selected_low_priority`: 126
- `omitted_candidate_gate_block`: 453
- `omitted_risk_entry_block`: 1
- `omitted_stale_leader`: 13
- `selected_concentrated`: 2
- `selected_main`: 10
- `selected_main_stale_review`: 1

## Current Selected

| ticker | bucket | main | concentrated | pressure | months main / conc |
|---|---|---:|---:|---:|---:|
| PR | `selected_main` | 4.0% | 0.0% | 0.662 | 5 / 4 |
| VRT | `selected_main` | 6.5% | 0.0% | 0.636 | 11 / 2 |
| MRVL | `selected_main` | 5.2% | 0.0% | 0.632 | 0 / 0 |
| GEV | `selected_main` | 13.9% | 0.0% | 0.624 | 2 / 0 |
| LRCX | `selected_main_stale_review` | 5.1% | 0.0% | 0.622 | 49 / 39 |
| FTI | `selected_main` | 6.5% | 0.0% | 0.617 | 0 / 0 |
| RKLB | `selected_main` | 5.9% | 0.0% | 0.545 | 0 / 0 |
| AKAM | `selected_main` | 3.6% | 0.0% | 0.538 | 1 / 0 |
| MLI | `selected_main` | 3.9% | 0.0% | 0.440 | 8 / 2 |
| HPE | `selected_main` | 3.6% | 0.0% | 0.412 | 0 / 0 |
| ENTG | `selected_main` | 3.6% | 0.0% | 0.283 | 0 / 0 |
| SNDK | `selected_concentrated` | 0.0% | 20.0% | 0.647 | 0 / 0 |
| WDC | `selected_concentrated` | 0.0% | 30.0% | 0.621 | 2 / 4 |

## Top Omitted Candidates

| ticker | bucket | pressure | score | conc score | monster | risk block | gate |
|---|---|---:|---:|---:|---:|---:|---|
| ETR | `not_selected_low_priority` | 0.662 | 3.989 | 0.000 | 0.579 | 0.000 | early_relaxed |
| LNG | `not_selected_low_priority` | 0.661 | 4.366 | 0.000 | 0.537 | 0.122 | future_relaxed |
| VZ | `not_selected_low_priority` | 0.658 | 4.022 | 0.000 | 0.595 | 0.000 | future_relaxed |
| CIEN | `not_selected_low_priority` | 0.647 | 2.995 | 0.000 | 0.562 | 0.333 | future_relaxed |
| ATO | `not_selected_low_priority` | 0.633 | 3.140 | 0.000 | 0.521 | 0.000 | future_relaxed |
| DTM | `not_selected_low_priority` | 0.629 | 2.554 | 0.000 | 0.545 | 0.133 | future_relaxed |
| CNQ | `not_selected_low_priority` | 0.627 | 2.138 | 0.000 | 0.583 | 0.108 | adr_global_alpha_fallback |
| OKE | `omitted_candidate_gate_block` | 0.626 | 2.167 | 0.000 | 0.551 | 0.014 | rejected |
| AMAT | `omitted_stale_leader` | 0.625 | 4.990 | 0.000 | 0.404 | 0.255 | core_strict |
| ROST | `not_selected_low_priority` | 0.625 | 2.824 | 0.000 | 0.524 | 0.242 | future_relaxed |
| SLB | `not_selected_low_priority` | 0.623 | 2.120 | 0.000 | 0.586 | 0.108 | future_relaxed |
| SU | `not_selected_low_priority` | 0.622 | 1.944 | 0.000 | 0.608 | 0.108 | adr_global_alpha_fallback |
| TRGP | `not_selected_low_priority` | 0.621 | 1.897 | 0.000 | 0.620 | 0.108 | future_relaxed |
| DAL | `omitted_candidate_gate_block` | 0.615 | 2.327 | 0.000 | 0.479 | 0.147 | rejected |
| NXT | `not_selected_low_priority` | 0.614 | 1.849 | 0.000 | 0.533 | 0.458 | future_relaxed |
| LITE | `not_selected_low_priority` | 0.613 | 2.313 | 0.000 | 0.530 | 0.333 | future_relaxed |
| CVX | `omitted_candidate_gate_block` | 0.605 | 4.241 | 0.000 | 0.504 | 0.108 | rejected |
| DUK | `not_selected_low_priority` | 0.604 | 3.376 | 0.000 | 0.495 | 0.000 | future_relaxed |
| ENB | `not_selected_low_priority` | 0.603 | 3.066 | 0.000 | 0.586 | 0.000 | adr_global_alpha_fallback |
| AM | `not_selected_low_priority` | 0.595 | 2.878 | 0.000 | 0.568 | 0.000 | early_relaxed |

## Interpretation

- Use `current_selected_audit.csv` to explain why current holdings were selected and whether any are stale-review names.
- Use `omitted_high_potential_candidates.csv` to inspect high-pressure candidates that were excluded by gates, risk blocks, caps, or lower priority.
- Use `historical_hold_persistence.csv` to distinguish long-held winners from newly selected names.
- This audit is intentionally explanatory only; it must not be used as a promotion gate without historical replay.
