# Selection Audit

Research-only diagnostic. It does not change production weights.

## Summary

- latest candidate rows: 607
- current main names: 13
- current concentrated names: 4
- selected stale review count: 3
- omitted monster candidates in top list: 0

## Decision Buckets

- `not_selected_low_priority`: 125
- `omitted_candidate_gate_block`: 459
- `omitted_risk_entry_block`: 1
- `omitted_stale_leader`: 10
- `selected_both`: 1
- `selected_concentrated`: 2
- `selected_main`: 6
- `selected_main_stale_review`: 3

## Current Selected

| ticker | bucket | main | concentrated | pressure | months main / conc |
|---|---|---:|---:|---:|---:|
| VRT | `selected_both` | 8.3% | 30.8% | 0.629 | 11 / 0 |
| GEV | `selected_main` | 13.2% | 0.0% | 0.623 | 1 / 0 |
| LRCX | `selected_main_stale_review` | 6.6% | 0.0% | 0.616 | 35 / 40 |
| FTI | `selected_main` | 5.1% | 0.0% | 0.605 | 1 / 0 |
| GOOG | `selected_main_stale_review` | 17.5% | 0.0% | 0.591 | 19 / 13 |
| AKAM | `selected_main` | 4.0% | 0.0% | 0.567 | 4 / 0 |
| AMZN | `selected_main` | 11.9% | 0.0% | 0.496 | 13 / 5 |
| PLTR | `selected_main_stale_review` | 8.3% | 0.0% | 0.428 | 12 / 5 |
| RKLB | `selected_main` | 5.9% | 0.0% | 0.423 | 3 / 0 |
| MLI | `selected_main` | 4.0% | 0.0% | 0.384 | 1 / 2 |
| WDC | `selected_concentrated` | 0.0% | 23.2% | 0.629 | 3 / 5 |
| MU | `selected_concentrated` | 0.0% | 19.1% | 0.584 | 5 / 5 |

## Top Omitted Candidates

| ticker | bucket | pressure | score | conc score | monster | risk block | gate |
|---|---|---:|---:|---:|---:|---:|---|
| LNG | `not_selected_low_priority` | 0.666 | 5.149 | 0.000 | 0.541 | 0.122 | future_relaxed |
| PR | `not_selected_low_priority` | 0.663 | 3.322 | 0.000 | 0.583 | 0.325 | early_relaxed |
| VZ | `not_selected_low_priority` | 0.660 | 4.296 | 0.000 | 0.595 | 0.000 | future_relaxed |
| ETR | `not_selected_low_priority` | 0.659 | 3.549 | 0.000 | 0.578 | 0.000 | early_relaxed |
| SLB | `not_selected_low_priority` | 0.649 | 2.999 | 0.000 | 0.582 | 0.108 | future_relaxed |
| SNDK | `omitted_candidate_gate_block` | 0.648 | 3.289 | 0.000 | 0.493 | 0.333 | rejected |
| OKE | `omitted_candidate_gate_block` | 0.645 | 2.711 | 0.000 | 0.549 | 0.014 | rejected |
| CNQ | `not_selected_low_priority` | 0.643 | 2.467 | 0.000 | 0.586 | 0.108 | adr_global_alpha_fallback |
| SU | `not_selected_low_priority` | 0.638 | 2.096 | 0.000 | 0.612 | 0.108 | adr_global_alpha_fallback |
| DAL | `omitted_candidate_gate_block` | 0.637 | 3.084 | 0.000 | 0.478 | 0.147 | rejected |
| MRVL | `omitted_candidate_gate_block` | 0.630 | 2.980 | 0.000 | 0.549 | 0.133 | rejected |
| TRGP | `not_selected_low_priority` | 0.627 | 1.792 | 0.000 | 0.619 | 0.108 | future_relaxed |
| CIEN | `not_selected_low_priority` | 0.627 | 1.838 | 0.000 | 0.561 | 0.333 | future_relaxed |
| ROST | `not_selected_low_priority` | 0.623 | 2.492 | 0.000 | 0.523 | 0.242 | future_relaxed |
| ATO | `not_selected_low_priority` | 0.618 | 2.295 | 0.000 | 0.517 | 0.000 | future_relaxed |
| AMAT | `omitted_stale_leader` | 0.617 | 4.409 | 0.000 | 0.393 | 0.255 | core_strict |
| CVX | `omitted_candidate_gate_block` | 0.608 | 4.722 | 0.000 | 0.506 | 0.108 | rejected |
| ED | `omitted_candidate_gate_block` | 0.605 | 2.081 | 0.000 | 0.507 | 0.000 | rejected |
| FANG | `not_selected_low_priority` | 0.604 | 2.544 | 0.000 | 0.590 | 0.108 | future_relaxed |
| DUK | `not_selected_low_priority` | 0.604 | 3.227 | 0.000 | 0.490 | 0.000 | future_relaxed |

## Interpretation

- Use `current_selected_audit.csv` to explain why current holdings were selected and whether any are stale-review names.
- Use `omitted_high_potential_candidates.csv` to inspect high-pressure candidates that were excluded by gates, risk blocks, caps, or lower priority.
- Use `historical_hold_persistence.csv` to distinguish long-held winners from newly selected names.
- This audit is intentionally explanatory only; it must not be used as a promotion gate without historical replay.
