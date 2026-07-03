# P4 Replacement-Quality Hook Implementation Note

## Status

Implemented as a default-OFF research hook in `tools/run_alphaops_vnext_policy_replay.py`.

Environment flag:

- `PHASE_CONCENTRATED_REPLACEMENT_QUALITY_ENABLED=1`

Optional thresholds:

- `R1000_CONC_REPLACEMENT_QUALITY_RANK_MAX` default `15`
- `R1000_CONC_REPLACEMENT_QUALITY_MIN_REVENUE_GROWTH` default `0.10`
- `R1000_CONC_REPLACEMENT_QUALITY_MAX_SWAPS_PER_DATE` default `1`

## Rule

The hook is Concentrated-only and preserves cash/stock gross by replacing at most one existing non-cash slot per rebalance date.

Candidate eligibility is PIT-only:

- candidate must be unheld
- same-month live rejection reason must be replacement/cap adjacent:
  - `hold_replace_threshold_not_met`
  - `leadership_persistence_hold_threshold_not_met`
  - `concentrated_emerging_or_top7_seat_cap`
- `leader_rank_ex_ante <= 15`
- `revenue_growth >= 0.10`
- existing Concentrated gates still apply through `allowed_candidate(...)`

The hook does not read `missed_leaders_audit.csv` and does not read forward-return labels.

## Probe

Cheap target-generation probe on run `28616190134`:

- command mode: `shadow_only`, `--skip-broker-replay`
- applied rows: `71`
- applied dates: `71`
- existing risk guard interaction observed: one generated `SCCO` replacement was removed by `neutral_metals_new_entry_block`

This probe only verifies wiring. It is not acceptance evidence because regenerated vNext target books are still not official-control reproducible.

## Required Next Gate

Before any fullrun or policy claim:

1. Run a cheap broker A/B for this hook.
2. Compare against a cash-carry comparable control.
3. Require `applied_count > 0`.
4. Require Concentrated CAGR `>= 50%`, MDD `>= -25%`.
5. Require OOS/IS non-deterioration and no single ticker/era dependency.

Until then this remains a parked default-OFF research hook.
