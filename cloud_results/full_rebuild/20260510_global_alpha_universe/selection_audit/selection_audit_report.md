# Selection Audit

Research-only diagnostic. It does not change production weights.

## Summary

- latest candidate rows: 604
- current main names: 17
- current concentrated names: 4
- selected stale review count: 3
- omitted monster candidates in top list: 0

## Decision Buckets

- `not_selected_low_priority`: 124
- `omitted_candidate_gate_block`: 456
- `omitted_risk_entry_block`: 1
- `omitted_stale_leader`: 10
- `selected_both`: 1
- `selected_concentrated`: 3
- `selected_main`: 6
- `selected_main_stale_review`: 3

## Current Selected

| ticker | bucket | main | concentrated | pressure | months main / conc |
|---|---|---:|---:|---:|---:|
| AKAM | `selected_both` | 4.0% | 34.2% | 0.569 | 0 / 0 |
| ETR | `selected_main` | 5.5% | 0.0% | 0.660 | 18 / 17 |
| PR | `selected_main` | 4.0% | 0.0% | 0.657 | 2 / 4 |
| VRT | `selected_main` | 6.1% | 0.0% | 0.629 | 11 / 2 |
| AMAT | `selected_main_stale_review` | 6.1% | 0.0% | 0.618 | 22 / 13 |
| LRCX | `selected_main_stale_review` | 5.9% | 0.0% | 0.617 | 42 / 39 |
| FTI | `selected_main` | 5.6% | 0.0% | 0.609 | 0 / 0 |
| GOOGL | `selected_main_stale_review` | 18.0% | 0.0% | 0.577 | 34 / 14 |
| PWR | `selected_main` | 5.6% | 0.0% | 0.412 | 5 / 0 |
| MLI | `selected_main` | 4.0% | 0.0% | 0.404 | 4 / 4 |
| SNDK | `selected_concentrated` | 0.0% | 15.4% | 0.645 | 0 / 0 |
| WDC | `selected_concentrated` | 0.0% | 27.5% | 0.632 | 4 / 5 |
| MU | `selected_concentrated` | 0.0% | 22.9% | 0.587 | 6 / 5 |

## Top Omitted Candidates

| ticker | bucket | pressure | score | conc score | monster | risk block | gate |
|---|---|---:|---:|---:|---:|---:|---|
| LNG | `not_selected_low_priority` | 0.666 | 4.986 | 0.000 | 0.541 | 0.122 | future_relaxed |
| VZ | `not_selected_low_priority` | 0.662 | 4.243 | 0.000 | 0.594 | 0.000 | future_relaxed |
| SLB | `not_selected_low_priority` | 0.645 | 2.834 | 0.000 | 0.581 | 0.108 | future_relaxed |
| OKE | `omitted_candidate_gate_block` | 0.644 | 2.654 | 0.000 | 0.548 | 0.014 | rejected |
| CNQ | `not_selected_low_priority` | 0.639 | 2.277 | 0.000 | 0.586 | 0.108 | adr_global_alpha_fallback |
| MRVL | `omitted_candidate_gate_block` | 0.636 | 3.203 | 0.000 | 0.550 | 0.133 | rejected |
| SU | `not_selected_low_priority` | 0.633 | 1.932 | 0.000 | 0.612 | 0.108 | adr_global_alpha_fallback |
| DAL | `omitted_candidate_gate_block` | 0.630 | 2.766 | 0.000 | 0.478 | 0.147 | rejected |
| CIEN | `not_selected_low_priority` | 0.626 | 1.881 | 0.000 | 0.559 | 0.333 | future_relaxed |
| TRGP | `not_selected_low_priority` | 0.624 | 1.735 | 0.000 | 0.618 | 0.108 | future_relaxed |
| ATO | `not_selected_low_priority` | 0.622 | 2.331 | 0.000 | 0.519 | 0.000 | future_relaxed |
| GEV | `omitted_candidate_gate_block` | 0.622 | 4.218 | 0.000 | 0.468 | 0.242 | rejected |
| ROST | `not_selected_low_priority` | 0.617 | 2.161 | 0.000 | 0.522 | 0.242 | future_relaxed |
| LITE | `not_selected_low_priority` | 0.610 | 1.983 | 0.000 | 0.521 | 0.333 | future_relaxed |
| ED | `omitted_candidate_gate_block` | 0.609 | 2.159 | 0.000 | 0.507 | 0.000 | rejected |
| CVX | `omitted_candidate_gate_block` | 0.609 | 4.681 | 0.000 | 0.506 | 0.108 | rejected |
| DUK | `not_selected_low_priority` | 0.608 | 3.275 | 0.000 | 0.495 | 0.000 | future_relaxed |
| ENB | `not_selected_low_priority` | 0.605 | 2.847 | 0.000 | 0.587 | 0.000 | adr_global_alpha_fallback |
| DTM | `not_selected_low_priority` | 0.603 | 1.615 | 0.000 | 0.541 | 0.133 | future_relaxed |
| FANG | `not_selected_low_priority` | 0.603 | 2.428 | 0.000 | 0.590 | 0.108 | future_relaxed |

## Interpretation

- Use `current_selected_audit.csv` to explain why current holdings were selected and whether any are stale-review names.
- Use `omitted_high_potential_candidates.csv` to inspect high-pressure candidates that were excluded by gates, risk blocks, caps, or lower priority.
- Use `historical_hold_persistence.csv` to distinguish long-held winners from newly selected names.
- This audit is intentionally explanatory only; it must not be used as a promotion gate without historical replay.
