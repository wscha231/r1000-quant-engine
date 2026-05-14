# Selection Audit

Research-only diagnostic. It does not change production weights.

## Summary

- latest candidate rows: 606
- current main names: 17
- current concentrated names: 3
- selected stale review count: 1
- omitted monster candidates in top list: 0

## Decision Buckets

- `not_selected_low_priority`: 124
- `omitted_candidate_gate_block`: 457
- `omitted_risk_entry_block`: 1
- `omitted_stale_leader`: 12
- `selected_concentrated`: 2
- `selected_main`: 9
- `selected_main_stale_review`: 1

## Current Selected

| ticker | bucket | main | concentrated | pressure | months main / conc |
|---|---|---:|---:|---:|---:|
| PR | `selected_main` | 4.0% | 0.0% | 0.666 | 3 / 7 |
| MRVL | `selected_main` | 5.7% | 0.0% | 0.641 | 0 / 0 |
| VRT | `selected_main` | 5.7% | 0.0% | 0.632 | 9 / 0 |
| FTI | `selected_main` | 5.3% | 0.0% | 0.632 | 0 / 0 |
| GEV | `selected_main` | 14.0% | 0.0% | 0.624 | 2 / 0 |
| GOOGL | `selected_main_stale_review` | 14.0% | 0.0% | 0.578 | 29 / 13 |
| CBOE | `selected_main` | 5.2% | 0.0% | 0.489 | 3 / 4 |
| RKLB | `selected_main` | 5.4% | 0.0% | 0.479 | 2 / 0 |
| HPE | `selected_main` | 4.0% | 0.0% | 0.462 | 0 / 1 |
| MLI | `selected_main` | 4.0% | 0.0% | 0.389 | 7 / 4 |
| WDC | `selected_concentrated` | 0.0% | 25.0% | 0.635 | 5 / 5 |
| MU | `selected_concentrated` | 0.0% | 50.0% | 0.581 | 10 / 5 |

## Top Omitted Candidates

| ticker | bucket | pressure | score | conc score | monster | risk block | gate |
|---|---|---:|---:|---:|---:|---:|---|
| LNG | `not_selected_low_priority` | 0.667 | 5.876 | 0.000 | 0.539 | 0.122 | future_relaxed |
| VZ | `not_selected_low_priority` | 0.661 | 4.477 | 0.000 | 0.595 | 0.000 | future_relaxed |
| ETR | `not_selected_low_priority` | 0.658 | 3.654 | 0.000 | 0.578 | 0.000 | early_relaxed |
| CIEN | `not_selected_low_priority` | 0.654 | 3.298 | 0.000 | 0.559 | 0.333 | future_relaxed |
| SLB | `not_selected_low_priority` | 0.652 | 3.379 | 0.000 | 0.585 | 0.108 | future_relaxed |
| SNDK | `omitted_candidate_gate_block` | 0.650 | 3.770 | 0.000 | 0.490 | 0.333 | rejected |
| CNQ | `not_selected_low_priority` | 0.650 | 2.867 | 0.000 | 0.587 | 0.108 | adr_global_alpha_fallback |
| SU | `not_selected_low_priority` | 0.649 | 2.759 | 0.000 | 0.613 | 0.108 | adr_global_alpha_fallback |
| OKE | `omitted_candidate_gate_block` | 0.644 | 2.781 | 0.000 | 0.550 | 0.014 | rejected |
| DAL | `omitted_candidate_gate_block` | 0.639 | 3.351 | 0.000 | 0.478 | 0.147 | rejected |
| ROST | `not_selected_low_priority` | 0.637 | 3.401 | 0.000 | 0.522 | 0.242 | future_relaxed |
| TRGP | `not_selected_low_priority` | 0.635 | 2.099 | 0.000 | 0.619 | 0.108 | future_relaxed |
| MTDR | `not_selected_low_priority` | 0.631 | 2.344 | 0.000 | 0.523 | 0.339 | early_relaxed |
| ATO | `not_selected_low_priority` | 0.623 | 2.582 | 0.000 | 0.519 | 0.000 | future_relaxed |
| AMAT | `omitted_stale_leader` | 0.621 | 4.897 | 0.000 | 0.397 | 0.255 | core_strict |
| LRCX | `omitted_stale_leader` | 0.618 | 4.997 | 0.000 | 0.390 | 0.347 | core_strict |
| LITE | `not_selected_low_priority` | 0.614 | 2.290 | 0.000 | 0.522 | 0.333 | future_relaxed |
| ED | `omitted_candidate_gate_block` | 0.614 | 2.610 | 0.000 | 0.507 | 0.000 | rejected |
| PBR | `not_selected_low_priority` | 0.612 | 2.050 | 0.000 | 0.519 | 0.108 | adr_global_alpha_fallback |
| JBL | `not_selected_low_priority` | 0.612 | 1.765 | 0.000 | 0.541 | 0.133 | future_relaxed |

## Interpretation

- Use `current_selected_audit.csv` to explain why current holdings were selected and whether any are stale-review names.
- Use `omitted_high_potential_candidates.csv` to inspect high-pressure candidates that were excluded by gates, risk blocks, caps, or lower priority.
- Use `historical_hold_persistence.csv` to distinguish long-held winners from newly selected names.
- This audit is intentionally explanatory only; it must not be used as a promotion gate without historical replay.
