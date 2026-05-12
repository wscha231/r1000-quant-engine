# Selection Audit

Research-only diagnostic. It does not change production weights.

## Summary

- latest candidate rows: 606
- current main names: 17
- current concentrated names: 4
- selected stale review count: 2
- omitted monster candidates in top list: 0

## Decision Buckets

- `not_selected_low_priority`: 124
- `omitted_candidate_gate_block`: 456
- `omitted_risk_entry_block`: 1
- `omitted_stale_leader`: 11
- `selected_concentrated`: 3
- `selected_main`: 9
- `selected_main_stale_review`: 2

## Current Selected

| ticker | bucket | main | concentrated | pressure | months main / conc |
|---|---|---:|---:|---:|---:|
| PR | `selected_main` | 4.0% | 0.0% | 0.656 | 3 / 7 |
| VRT | `selected_main` | 6.0% | 0.0% | 0.630 | 11 / 0 |
| GEV | `selected_main` | 9.9% | 0.0% | 0.623 | 2 / 0 |
| LRCX | `selected_main_stale_review` | 4.6% | 0.0% | 0.619 | 37 / 39 |
| FTI | `selected_main` | 4.6% | 0.0% | 0.610 | 1 / 0 |
| GOOGL | `selected_main_stale_review` | 12.0% | 0.0% | 0.578 | 24 / 13 |
| AKAM | `selected_main` | 3.8% | 0.0% | 0.563 | 0 / 0 |
| AMZN | `selected_main` | 11.3% | 0.0% | 0.513 | 24 / 3 |
| CBOE | `selected_main` | 4.3% | 0.0% | 0.472 | 3 / 4 |
| PWR | `selected_main` | 4.5% | 0.0% | 0.415 | 2 / 0 |
| MLI | `selected_main` | 4.0% | 0.0% | 0.396 | 3 / 2 |
| SNDK | `selected_concentrated` | 0.0% | 17.0% | 0.642 | 0 / 0 |
| WDC | `selected_concentrated` | 0.0% | 26.6% | 0.624 | 2 / 5 |
| MU | `selected_concentrated` | 0.0% | 22.9% | 0.587 | 9 / 5 |

## Top Omitted Candidates

| ticker | bucket | pressure | score | conc score | monster | risk block | gate |
|---|---|---:|---:|---:|---:|---:|---|
| LNG | `not_selected_low_priority` | 0.663 | 4.645 | 0.000 | 0.541 | 0.122 | future_relaxed |
| VZ | `not_selected_low_priority` | 0.660 | 4.208 | 0.000 | 0.594 | 0.000 | future_relaxed |
| ETR | `not_selected_low_priority` | 0.659 | 3.406 | 0.000 | 0.577 | 0.000 | early_relaxed |
| SLB | `not_selected_low_priority` | 0.644 | 2.861 | 0.000 | 0.582 | 0.108 | future_relaxed |
| OKE | `omitted_candidate_gate_block` | 0.642 | 2.608 | 0.000 | 0.549 | 0.014 | rejected |
| DAL | `omitted_candidate_gate_block` | 0.637 | 3.088 | 0.000 | 0.478 | 0.147 | rejected |
| MRVL | `omitted_candidate_gate_block` | 0.637 | 3.285 | 0.000 | 0.551 | 0.133 | rejected |
| CNQ | `not_selected_low_priority` | 0.637 | 2.192 | 0.000 | 0.586 | 0.108 | adr_global_alpha_fallback |
| CIEN | `not_selected_low_priority` | 0.634 | 2.156 | 0.000 | 0.559 | 0.333 | future_relaxed |
| SU | `not_selected_low_priority` | 0.628 | 1.831 | 0.000 | 0.612 | 0.108 | adr_global_alpha_fallback |
| ATO | `not_selected_low_priority` | 0.622 | 2.297 | 0.000 | 0.518 | 0.000 | future_relaxed |
| ROST | `not_selected_low_priority` | 0.619 | 2.260 | 0.000 | 0.522 | 0.242 | future_relaxed |
| TRGP | `not_selected_low_priority` | 0.618 | 1.589 | 0.000 | 0.618 | 0.108 | future_relaxed |
| AMAT | `omitted_stale_leader` | 0.618 | 4.186 | 0.000 | 0.394 | 0.255 | core_strict |
| LITE | `not_selected_low_priority` | 0.610 | 2.002 | 0.000 | 0.521 | 0.333 | future_relaxed |
| ED | `omitted_candidate_gate_block` | 0.609 | 2.223 | 0.000 | 0.507 | 0.000 | rejected |
| DUK | `not_selected_low_priority` | 0.609 | 3.335 | 0.000 | 0.494 | 0.000 | future_relaxed |
| CVX | `omitted_candidate_gate_block` | 0.608 | 4.477 | 0.000 | 0.506 | 0.108 | rejected |
| UTHR | `not_selected_low_priority` | 0.604 | 1.504 | 0.000 | 0.556 | 0.242 | future_relaxed |
| ENB | `not_selected_low_priority` | 0.601 | 2.796 | 0.000 | 0.586 | 0.000 | adr_global_alpha_fallback |

## Interpretation

- Use `current_selected_audit.csv` to explain why current holdings were selected and whether any are stale-review names.
- Use `omitted_high_potential_candidates.csv` to inspect high-pressure candidates that were excluded by gates, risk blocks, caps, or lower priority.
- Use `historical_hold_persistence.csv` to distinguish long-held winners from newly selected names.
- This audit is intentionally explanatory only; it must not be used as a promotion gate without historical replay.
