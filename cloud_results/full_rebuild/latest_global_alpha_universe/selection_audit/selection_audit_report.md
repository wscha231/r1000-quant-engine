# Selection Audit

Research-only diagnostic. It does not change production weights.

## Summary

- latest candidate rows: 605
- current main names: 17
- current concentrated names: 3
- selected stale review count: 3
- omitted monster candidates in top list: 0

## Decision Buckets

- `not_selected_low_priority`: 129
- `omitted_candidate_gate_block`: 450
- `omitted_risk_entry_block`: 1
- `omitted_stale_leader`: 11
- `selected_concentrated`: 3
- `selected_main`: 8
- `selected_main_stale_review`: 3

## Current Selected

| ticker | bucket | main | concentrated | pressure | months main / conc |
|---|---|---:|---:|---:|---:|
| PR | `selected_main` | 4.0% | 0.0% | 0.631 | 6 / 7 |
| VRT | `selected_main` | 6.3% | 0.0% | 0.630 | 10 / 0 |
| GEV | `selected_main` | 6.3% | 0.0% | 0.620 | 2 / 0 |
| LRCX | `selected_main_stale_review` | 6.3% | 0.0% | 0.619 | 43 / 39 |
| AMAT | `selected_main_stale_review` | 6.3% | 0.0% | 0.617 | 19 / 9 |
| FTI | `selected_main` | 6.2% | 0.0% | 0.615 | 1 / 0 |
| DTM | `selected_main` | 4.0% | 0.0% | 0.601 | 11 / 7 |
| GOOG | `selected_main_stale_review` | 18.0% | 0.0% | 0.564 | 26 / 10 |
| KIM | `selected_main` | 4.0% | 0.0% | 0.550 | 0 / 0 |
| TER | `selected_main` | 4.0% | 0.0% | 0.541 | 0 / 8 |
| MLI | `selected_main` | 4.0% | 0.0% | 0.400 | 4 / 2 |
| SNDK | `selected_concentrated` | 0.0% | 20.4% | 0.640 | 0 / 0 |
| CIEN | `selected_concentrated` | 0.0% | 39.6% | 0.633 | 0 / 3 |
| WDC | `selected_concentrated` | 0.0% | 40.0% | 0.630 | 2 / 5 |

## Top Omitted Candidates

| ticker | bucket | pressure | score | conc score | monster | risk block | gate |
|---|---|---:|---:|---:|---:|---:|---|
| LNG | `not_selected_low_priority` | 0.664 | 4.785 | 0.000 | 0.541 | 0.122 | future_relaxed |
| VZ | `not_selected_low_priority` | 0.660 | 4.156 | 0.000 | 0.594 | 0.000 | future_relaxed |
| ETR | `not_selected_low_priority` | 0.656 | 3.274 | 0.000 | 0.577 | 0.000 | early_relaxed |
| SLB | `not_selected_low_priority` | 0.650 | 3.098 | 0.000 | 0.583 | 0.108 | future_relaxed |
| OKE | `omitted_candidate_gate_block` | 0.643 | 2.600 | 0.000 | 0.549 | 0.014 | rejected |
| CTRA | `not_selected_low_priority` | 0.638 | 2.258 | 0.000 | 0.599 | 0.108 | early_relaxed |
| MRVL | `omitted_candidate_gate_block` | 0.638 | 3.452 | 0.000 | 0.551 | 0.133 | rejected |
| DAL | `omitted_candidate_gate_block` | 0.632 | 2.786 | 0.000 | 0.478 | 0.147 | rejected |
| CNQ | `not_selected_low_priority` | 0.631 | 2.056 | 0.000 | 0.586 | 0.108 | adr_global_alpha_fallback |
| SU | `not_selected_low_priority` | 0.624 | 1.693 | 0.000 | 0.612 | 0.108 | adr_global_alpha_fallback |
| LITE | `not_selected_low_priority` | 0.622 | 2.441 | 0.000 | 0.523 | 0.333 | future_relaxed |
| ATO | `not_selected_low_priority` | 0.621 | 2.348 | 0.000 | 0.518 | 0.000 | future_relaxed |
| ROST | `not_selected_low_priority` | 0.614 | 2.161 | 0.000 | 0.521 | 0.242 | future_relaxed |
| DUK | `not_selected_low_priority` | 0.608 | 3.387 | 0.000 | 0.494 | 0.000 | future_relaxed |
| CVX | `omitted_candidate_gate_block` | 0.608 | 4.679 | 0.000 | 0.505 | 0.108 | rejected |
| FANG | `not_selected_low_priority` | 0.606 | 2.809 | 0.000 | 0.589 | 0.108 | future_relaxed |
| ED | `omitted_candidate_gate_block` | 0.606 | 2.141 | 0.000 | 0.506 | 0.000 | rejected |
| ENB | `not_selected_low_priority` | 0.602 | 2.779 | 0.000 | 0.587 | 0.000 | adr_global_alpha_fallback |
| TRGP | `not_selected_low_priority` | 0.601 | 1.164 | 0.000 | 0.618 | 0.108 | future_relaxed |
| MTDR | `not_selected_low_priority` | 0.596 | 1.299 | 0.000 | 0.524 | 0.339 | early_relaxed |

## Interpretation

- Use `current_selected_audit.csv` to explain why current holdings were selected and whether any are stale-review names.
- Use `omitted_high_potential_candidates.csv` to inspect high-pressure candidates that were excluded by gates, risk blocks, caps, or lower priority.
- Use `historical_hold_persistence.csv` to distinguish long-held winners from newly selected names.
- This audit is intentionally explanatory only; it must not be used as a promotion gate without historical replay.
