# Selection Audit

Research-only diagnostic. It does not change production weights.

## Summary

- latest candidate rows: 606
- current main names: 17
- current concentrated names: 3
- selected stale review count: 3
- omitted monster candidates in top list: 0

## Decision Buckets

- `not_selected_low_priority`: 124
- `omitted_candidate_gate_block`: 458
- `omitted_risk_entry_block`: 1
- `omitted_stale_leader`: 10
- `selected_concentrated`: 2
- `selected_main`: 8
- `selected_main_stale_review`: 3

## Current Selected

| ticker | bucket | main | concentrated | pressure | months main / conc |
|---|---|---:|---:|---:|---:|
| PR | `selected_main` | 4.0% | 0.0% | 0.661 | 4 / 4 |
| OKE | `selected_main` | 5.6% | 0.0% | 0.640 | 1 / 0 |
| SU | `selected_main` | 5.6% | 0.0% | 0.637 | 0 / 0 |
| VRT | `selected_main` | 6.1% | 0.0% | 0.630 | 11 / 2 |
| LRCX | `selected_main_stale_review` | 6.1% | 0.0% | 0.620 | 40 / 39 |
| FTI | `selected_main` | 5.7% | 0.0% | 0.606 | 1 / 0 |
| GOOG | `selected_main_stale_review` | 17.9% | 0.0% | 0.571 | 31 / 13 |
| AKAM | `selected_main` | 4.0% | 0.0% | 0.569 | 4 / 0 |
| PLTR | `selected_main_stale_review` | 6.1% | 0.0% | 0.427 | 11 / 5 |
| PWR | `selected_main` | 5.7% | 0.0% | 0.409 | 7 / 0 |
| MLI | `selected_main` | 4.0% | 0.0% | 0.404 | 4 / 2 |
| WDC | `selected_concentrated` | 0.0% | 35.7% | 0.629 | 4 / 5 |
| MU | `selected_concentrated` | 0.0% | 26.5% | 0.590 | 9 / 5 |

## Top Omitted Candidates

| ticker | bucket | pressure | score | conc score | monster | risk block | gate |
|---|---|---:|---:|---:|---:|---:|---|
| LNG | `not_selected_low_priority` | 0.665 | 4.716 | 0.000 | 0.540 | 0.122 | future_relaxed |
| VZ | `not_selected_low_priority` | 0.661 | 4.249 | 0.000 | 0.596 | 0.000 | future_relaxed |
| ETR | `not_selected_low_priority` | 0.659 | 3.486 | 0.000 | 0.577 | 0.000 | early_relaxed |
| SNDK | `omitted_candidate_gate_block` | 0.646 | 3.174 | 0.000 | 0.492 | 0.333 | rejected |
| SLB | `not_selected_low_priority` | 0.642 | 2.576 | 0.000 | 0.581 | 0.108 | future_relaxed |
| CNQ | `not_selected_low_priority` | 0.639 | 2.236 | 0.000 | 0.585 | 0.108 | adr_global_alpha_fallback |
| DAL | `omitted_candidate_gate_block` | 0.634 | 2.898 | 0.000 | 0.478 | 0.147 | rejected |
| MRVL | `omitted_candidate_gate_block` | 0.627 | 2.833 | 0.000 | 0.550 | 0.133 | rejected |
| ATO | `not_selected_low_priority` | 0.621 | 2.273 | 0.000 | 0.517 | 0.000 | future_relaxed |
| ROST | `not_selected_low_priority` | 0.621 | 2.276 | 0.000 | 0.522 | 0.242 | future_relaxed |
| GEV | `omitted_candidate_gate_block` | 0.620 | 4.053 | 0.000 | 0.468 | 0.242 | rejected |
| AMAT | `omitted_stale_leader` | 0.619 | 4.273 | 0.000 | 0.395 | 0.255 | core_strict |
| TRGP | `not_selected_low_priority` | 0.614 | 1.462 | 0.000 | 0.617 | 0.108 | future_relaxed |
| DUK | `not_selected_low_priority` | 0.609 | 3.271 | 0.000 | 0.493 | 0.000 | future_relaxed |
| CVX | `omitted_candidate_gate_block` | 0.608 | 4.480 | 0.000 | 0.506 | 0.108 | rejected |
| ED | `omitted_candidate_gate_block` | 0.607 | 2.149 | 0.000 | 0.506 | 0.000 | rejected |
| CIEN | `not_selected_low_priority` | 0.605 | 1.332 | 0.000 | 0.559 | 0.333 | future_relaxed |
| ENB | `not_selected_low_priority` | 0.602 | 2.801 | 0.000 | 0.586 | 0.000 | adr_global_alpha_fallback |
| FANG | `not_selected_low_priority` | 0.601 | 2.303 | 0.000 | 0.589 | 0.108 | future_relaxed |
| DTM | `not_selected_low_priority` | 0.598 | 1.517 | 0.000 | 0.540 | 0.133 | future_relaxed |

## Interpretation

- Use `current_selected_audit.csv` to explain why current holdings were selected and whether any are stale-review names.
- Use `omitted_high_potential_candidates.csv` to inspect high-pressure candidates that were excluded by gates, risk blocks, caps, or lower priority.
- Use `historical_hold_persistence.csv` to distinguish long-held winners from newly selected names.
- This audit is intentionally explanatory only; it must not be used as a promotion gate without historical replay.
