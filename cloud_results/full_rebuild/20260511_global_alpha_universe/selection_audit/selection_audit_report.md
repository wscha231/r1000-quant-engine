# Selection Audit

Research-only diagnostic. It does not change production weights.

## Summary

- latest candidate rows: 604
- current main names: 17
- current concentrated names: 5
- selected stale review count: 2
- omitted monster candidates in top list: 0

## Decision Buckets

- `not_selected_low_priority`: 124
- `omitted_candidate_gate_block`: 456
- `omitted_risk_entry_block`: 1
- `omitted_stale_leader`: 11
- `selected_both`: 1
- `selected_concentrated`: 3
- `selected_main`: 6
- `selected_main_stale_review`: 2

## Current Selected

| ticker | bucket | main | concentrated | pressure | months main / conc |
|---|---|---:|---:|---:|---:|
| AKAM | `selected_both` | 4.0% | 25.5% | 0.573 | 1 / 0 |
| PR | `selected_main` | 4.0% | 0.0% | 0.656 | 2 / 4 |
| VRT | `selected_main` | 6.1% | 0.0% | 0.623 | 11 / 0 |
| LRCX | `selected_main_stale_review` | 6.1% | 0.0% | 0.616 | 48 / 52 |
| FTI | `selected_main` | 5.6% | 0.0% | 0.610 | 1 / 0 |
| GOOGL | `selected_main_stale_review` | 18.0% | 0.0% | 0.578 | 35 / 19 |
| CBOE | `selected_main` | 5.5% | 0.0% | 0.471 | 5 / 3 |
| PWR | `selected_main` | 5.6% | 0.0% | 0.412 | 12 / 0 |
| MLI | `selected_main` | 4.0% | 0.0% | 0.399 | 1 / 3 |
| SNDK | `selected_concentrated` | 0.0% | 10.6% | 0.646 | 0 / 0 |
| WDC | `selected_concentrated` | 0.0% | 20.9% | 0.627 | 1 / 5 |
| MU | `selected_concentrated` | 0.0% | 17.2% | 0.587 | 8 / 4 |

## Top Omitted Candidates

| ticker | bucket | pressure | score | conc score | monster | risk block | gate |
|---|---|---:|---:|---:|---:|---:|---|
| LNG | `not_selected_low_priority` | 0.665 | 4.804 | 0.000 | 0.541 | 0.122 | future_relaxed |
| VZ | `not_selected_low_priority` | 0.661 | 4.185 | 0.000 | 0.594 | 0.000 | future_relaxed |
| ETR | `not_selected_low_priority` | 0.659 | 3.401 | 0.000 | 0.576 | 0.000 | early_relaxed |
| SLB | `not_selected_low_priority` | 0.644 | 2.813 | 0.000 | 0.581 | 0.108 | future_relaxed |
| OKE | `omitted_candidate_gate_block` | 0.641 | 2.500 | 0.000 | 0.548 | 0.014 | rejected |
| CNQ | `not_selected_low_priority` | 0.637 | 2.204 | 0.000 | 0.585 | 0.108 | adr_global_alpha_fallback |
| DAL | `omitted_candidate_gate_block` | 0.635 | 2.956 | 0.000 | 0.477 | 0.147 | rejected |
| MRVL | `omitted_candidate_gate_block` | 0.633 | 3.053 | 0.000 | 0.549 | 0.133 | rejected |
| SU | `not_selected_low_priority` | 0.630 | 1.871 | 0.000 | 0.611 | 0.108 | adr_global_alpha_fallback |
| TRGP | `not_selected_low_priority` | 0.622 | 1.641 | 0.000 | 0.617 | 0.108 | future_relaxed |
| ROST | `not_selected_low_priority` | 0.622 | 2.431 | 0.000 | 0.522 | 0.242 | future_relaxed |
| GEV | `omitted_candidate_gate_block` | 0.620 | 4.113 | 0.000 | 0.467 | 0.242 | rejected |
| ATO | `not_selected_low_priority` | 0.620 | 2.315 | 0.000 | 0.518 | 0.000 | future_relaxed |
| CIEN | `not_selected_low_priority` | 0.618 | 1.655 | 0.000 | 0.559 | 0.333 | future_relaxed |
| AMAT | `omitted_stale_leader` | 0.615 | 3.975 | 0.000 | 0.393 | 0.255 | core_strict |
| DUK | `not_selected_low_priority` | 0.610 | 3.382 | 0.000 | 0.495 | 0.000 | future_relaxed |
| ED | `omitted_candidate_gate_block` | 0.609 | 2.179 | 0.000 | 0.507 | 0.000 | rejected |
| CVX | `omitted_candidate_gate_block` | 0.608 | 4.605 | 0.000 | 0.505 | 0.108 | rejected |
| ENB | `not_selected_low_priority` | 0.603 | 2.815 | 0.000 | 0.586 | 0.000 | adr_global_alpha_fallback |
| FANG | `not_selected_low_priority` | 0.602 | 2.476 | 0.000 | 0.589 | 0.108 | future_relaxed |

## Interpretation

- Use `current_selected_audit.csv` to explain why current holdings were selected and whether any are stale-review names.
- Use `omitted_high_potential_candidates.csv` to inspect high-pressure candidates that were excluded by gates, risk blocks, caps, or lower priority.
- Use `historical_hold_persistence.csv` to distinguish long-held winners from newly selected names.
- This audit is intentionally explanatory only; it must not be used as a promotion gate without historical replay.
