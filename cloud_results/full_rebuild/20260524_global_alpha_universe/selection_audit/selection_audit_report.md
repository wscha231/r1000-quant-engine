# Selection Audit

Research-only diagnostic. It does not change production weights.

## Summary

- latest candidate rows: 571
- current main names: 14
- current concentrated names: 3
- selected stale review count: 2
- omitted monster candidates in top list: 0

## Decision Buckets

- `not_selected_low_priority`: 117
- `omitted_candidate_gate_block`: 433
- `omitted_stale_leader`: 12
- `selected_both`: 1
- `selected_concentrated`: 1
- `selected_main`: 5
- `selected_main_stale_review`: 2

## Current Selected

| ticker | bucket | main | concentrated | pressure | months main / conc |
|---|---|---:|---:|---:|---:|
| MRVL | `selected_both` | 7.4% | 42.4% | 0.638 | 0 / 0 |
| VRT | `selected_main` | 12.4% | 0.0% | 0.646 | 10 / 0 |
| GEV | `selected_main` | 11.5% | 0.0% | 0.629 | 1 / 0 |
| AMD | `selected_main_stale_review` | 7.4% | 0.0% | 0.584 | 3 / 3 |
| GOOG | `selected_main_stale_review` | 19.8% | 0.0% | 0.568 | 22 / 15 |
| RKLB | `selected_main` | 4.9% | 0.0% | 0.521 | 3 / 0 |
| HPE | `selected_main` | 3.8% | 0.0% | 0.414 | 0 / 0 |
| MLI | `selected_main` | 3.9% | 0.0% | 0.378 | 7 / 6 |
| MTSI | `selected_concentrated` | 0.0% | 15.4% | 0.481 | 0 / 2 |

## Top Omitted Candidates

| ticker | bucket | pressure | score | conc score | monster | risk block | gate |
|---|---|---:|---:|---:|---:|---:|---|
| LNG | `not_selected_low_priority` | 0.665 | 5.230 | 0.000 | 0.531 | 0.122 | future_relaxed |
| CIEN | `not_selected_low_priority` | 0.663 | 3.830 | 0.000 | 0.563 | 0.333 | future_relaxed |
| PR | `not_selected_low_priority` | 0.658 | 2.950 | 0.000 | 0.580 | 0.325 | early_relaxed |
| VZ | `not_selected_low_priority` | 0.657 | 3.942 | 0.000 | 0.589 | 0.000 | future_relaxed |
| ETR | `not_selected_low_priority` | 0.649 | 2.823 | 0.000 | 0.575 | 0.000 | early_relaxed |
| SNDK | `omitted_candidate_gate_block` | 0.647 | 3.398 | 0.000 | 0.486 | 0.333 | rejected |
| SLB | `omitted_candidate_gate_block` | 0.646 | 2.957 | 0.000 | 0.575 | 0.108 | rejected |
| CNQ | `not_selected_low_priority` | 0.645 | 2.451 | 0.000 | 0.584 | 0.108 | adr_global_alpha_fallback |
| OKE | `omitted_candidate_gate_block` | 0.644 | 2.684 | 0.000 | 0.543 | 0.014 | rejected |
| DAL | `omitted_candidate_gate_block` | 0.643 | 3.475 | 0.000 | 0.475 | 0.147 | rejected |
| SU | `not_selected_low_priority` | 0.643 | 2.174 | 0.000 | 0.609 | 0.108 | adr_global_alpha_fallback |
| WDC | `not_selected_low_priority` | 0.637 | 4.649 | 0.000 | 0.422 | 0.347 | future_relaxed |
| ROST | `not_selected_low_priority` | 0.635 | 2.970 | 0.000 | 0.523 | 0.242 | future_relaxed |
| LITE | `not_selected_low_priority` | 0.633 | 2.963 | 0.000 | 0.520 | 0.333 | future_relaxed |
| TRGP | `not_selected_low_priority` | 0.632 | 1.790 | 0.000 | 0.612 | 0.108 | future_relaxed |
| FTI | `not_selected_low_priority` | 0.630 | 1.686 | 0.000 | 0.577 | 0.108 | future_relaxed |
| MTDR | `not_selected_low_priority` | 0.626 | 1.919 | 0.000 | 0.519 | 0.339 | early_relaxed |
| NXT | `not_selected_low_priority` | 0.623 | 1.684 | 0.000 | 0.525 | 0.458 | future_relaxed |
| AMAT | `omitted_stale_leader` | 0.620 | 4.320 | 0.000 | 0.397 | 0.255 | core_strict |
| ATO | `not_selected_low_priority` | 0.615 | 2.062 | 0.000 | 0.508 | 0.000 | future_relaxed |

## Interpretation

- Use `current_selected_audit.csv` to explain why current holdings were selected and whether any are stale-review names.
- Use `omitted_high_potential_candidates.csv` to inspect high-pressure candidates that were excluded by gates, risk blocks, caps, or lower priority.
- Use `historical_hold_persistence.csv` to distinguish long-held winners from newly selected names.
- This audit is intentionally explanatory only; it must not be used as a promotion gate without historical replay.
