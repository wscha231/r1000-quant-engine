# Selection Audit

Research-only diagnostic. It does not change production weights.

## Summary

- latest candidate rows: 608
- current main names: 17
- current concentrated names: 5
- selected stale review count: 3
- omitted monster candidates in top list: 0

## Decision Buckets

- `not_selected_low_priority`: 126
- `omitted_candidate_gate_block`: 458
- `omitted_risk_entry_block`: 1
- `omitted_stale_leader`: 9
- `selected_both`: 1
- `selected_concentrated`: 3
- `selected_main`: 7
- `selected_main_stale_review`: 3

## Current Selected

| ticker | bucket | main | concentrated | pressure | months main / conc |
|---|---|---:|---:|---:|---:|
| MRVL | `selected_both` | 6.7% | 12.5% | 0.641 | 0 / 0 |
| PR | `selected_main` | 4.0% | 0.0% | 0.665 | 4 / 5 |
| FTI | `selected_main` | 6.4% | 0.0% | 0.638 | 1 / 0 |
| VRT | `selected_main` | 6.7% | 0.0% | 0.638 | 13 / 3 |
| LRCX | `selected_main_stale_review` | 6.6% | 0.0% | 0.621 | 47 / 43 |
| AMD | `selected_main_stale_review` | 4.0% | 0.0% | 0.596 | 12 / 0 |
| GOOG | `selected_main_stale_review` | 16.0% | 0.0% | 0.574 | 11 / 14 |
| CBOE | `selected_main` | 6.4% | 0.0% | 0.482 | 3 / 3 |
| HPE | `selected_main` | 4.0% | 0.0% | 0.477 | 0 / 0 |
| PWR | `selected_main` | 6.4% | 0.0% | 0.448 | 7 / 0 |
| MLI | `selected_main` | 4.0% | 0.0% | 0.390 | 6 / 2 |
| CIEN | `selected_concentrated` | 0.0% | 12.5% | 0.654 | 0 / 4 |
| MU | `selected_concentrated` | 0.0% | 12.5% | 0.589 | 10 / 5 |
| NVDA | `selected_concentrated` | 0.0% | 12.5% | 0.552 | 49 / 25 |

## Top Omitted Candidates

| ticker | bucket | pressure | score | conc score | monster | risk block | gate |
|---|---|---:|---:|---:|---:|---:|---|
| LNG | `not_selected_low_priority` | 0.667 | 5.643 | 0.000 | 0.541 | 0.122 | future_relaxed |
| VZ | `not_selected_low_priority` | 0.660 | 4.391 | 0.000 | 0.595 | 0.000 | future_relaxed |
| ETR | `not_selected_low_priority` | 0.655 | 3.486 | 0.000 | 0.576 | 0.000 | early_relaxed |
| CNQ | `not_selected_low_priority` | 0.648 | 2.833 | 0.000 | 0.588 | 0.108 | adr_global_alpha_fallback |
| SNDK | `omitted_candidate_gate_block` | 0.648 | 4.094 | 0.000 | 0.480 | 0.333 | rejected |
| SU | `not_selected_low_priority` | 0.646 | 2.695 | 0.000 | 0.611 | 0.108 | adr_global_alpha_fallback |
| SLB | `not_selected_low_priority` | 0.645 | 3.047 | 0.000 | 0.583 | 0.108 | future_relaxed |
| DAL | `omitted_candidate_gate_block` | 0.642 | 3.583 | 0.000 | 0.478 | 0.147 | rejected |
| TRGP | `not_selected_low_priority` | 0.641 | 2.283 | 0.000 | 0.617 | 0.108 | future_relaxed |
| OKE | `omitted_candidate_gate_block` | 0.638 | 2.601 | 0.000 | 0.549 | 0.014 | rejected |
| ROST | `not_selected_low_priority` | 0.632 | 3.169 | 0.000 | 0.520 | 0.242 | future_relaxed |
| WDC | `not_selected_low_priority` | 0.631 | 4.338 | 0.000 | 0.416 | 0.347 | future_relaxed |
| LITE | `not_selected_low_priority` | 0.631 | 2.883 | 0.000 | 0.527 | 0.333 | future_relaxed |
| NXT | `not_selected_low_priority` | 0.627 | 2.125 | 0.000 | 0.517 | 0.458 | future_relaxed |
| GEV | `omitted_candidate_gate_block` | 0.626 | 5.269 | 0.000 | 0.469 | 0.242 | rejected |
| AMAT | `omitted_stale_leader` | 0.625 | 5.051 | 0.000 | 0.402 | 0.255 | core_strict |
| MTDR | `not_selected_low_priority` | 0.623 | 2.058 | 0.000 | 0.522 | 0.339 | early_relaxed |
| UTHR | `not_selected_low_priority` | 0.618 | 1.868 | 0.000 | 0.557 | 0.242 | future_relaxed |
| ATO | `not_selected_low_priority` | 0.618 | 2.392 | 0.000 | 0.515 | 0.000 | future_relaxed |
| JBL | `not_selected_low_priority` | 0.616 | 2.028 | 0.000 | 0.529 | 0.133 | future_relaxed |

## Interpretation

- Use `current_selected_audit.csv` to explain why current holdings were selected and whether any are stale-review names.
- Use `omitted_high_potential_candidates.csv` to inspect high-pressure candidates that were excluded by gates, risk blocks, caps, or lower priority.
- Use `historical_hold_persistence.csv` to distinguish long-held winners from newly selected names.
- This audit is intentionally explanatory only; it must not be used as a promotion gate without historical replay.
