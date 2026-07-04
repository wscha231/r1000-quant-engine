# Policy-Path Combo Candidate - 2026-07-04

## Status

Research-only policy-path probe. No fullrun was dispatched. No production or
live state was changed.

This probe maps the fixed-book replay candidates into default-off policy-path
hooks and measures the generated target books with broker replay.

## Contract

- Source artifact: `artifacts/fullrun_28436307420/official/outputs`
- Candidate book:
  `artifacts/fullrun_28436307420/official/outputs/sec_enriched_candidate_replay/candidate_replay_book_sec_enriched.csv`
- Price cache: `outputs/phase1_replay_goal_test/cache_prices`
- Cash rate: `cache_macro/fred_dgs3mo_DGS3MO.parquet`
- Replay end: `2026-06-29`
- Fill mode: `next_close`
- Cost: `25 bps`
- Metric mode: `broker_ledger_next_close_cash_carry`
- Production activation: false

## Enabled Research Hooks

Main:

- `PHASE_MAIN_POST_SELECTION_TOPN_FILTER_ENABLED=1`
- `R1000_MAIN_POST_SELECTION_TOP_N=14`
- `PHASE_AI_CAPEX_MOMENTUM_TILT_ENABLED=1`
- `R1000_MAIN_AI_CAPEX_TILT_STRENGTH=0.20`

Concentrated:

- `PHASE_CONCENTRATED_REPLACEMENT_QUALITY_ENABLED=1`
- `PHASE_CONCENTRATED_CASHFUNDED_EARLY_ENTRY_ENABLED=1`
- `R1000_CONC_CASHFUNDED_EARLY_ENTRY_ADD_WEIGHT=0.058`
- `R1000_CONC_CASHFUNDED_EARLY_ENTRY_MIN_BREAKOUT_QUALITY=0.50`

The final generated target books are in:

- `outputs/policy_path_combo_probe_20260704_final_candidate/official_main_target_book.csv`
- `outputs/policy_path_combo_probe_20260704_final_candidate/official_concentrated_target_book.csv`

Broker outputs:

- `outputs/policy_path_combo_probe_20260704_final_candidate/broker_main_cash_carry/metrics.json`
- `outputs/policy_path_combo_probe_20260704_final_candidate/broker_concentrated_cash_carry/metrics.json`

## Main Calibration Notes

`--main-target-n 14` did not reproduce the fixed-book top14 mechanism. It
changes upstream selection. The working policy-path mapping is a post-selection
topN filter: build normal Main N15 first, then drop the smallest tail names to
implicit cash.

Small Main grid:

| Arm | CAGR | MaxDD | Sharpe | Verdict |
|---|---:|---:|---:|---|
| top13 + tilt05 | 32.99% | -25.40% | 1.264 | reject |
| top13 + tilt10 | 33.35% | -25.27% | 1.270 | reject |
| top13 + tilt15 | 33.58% | -25.27% | 1.273 | reject |
| top14 + tilt05 | 35.47% | -25.11% | 1.300 | reject |
| top14 + tilt15 | 36.07% | -25.01% | 1.309 | near miss |
| top14 + tilt20 | 36.33% | -24.91% | 1.312 | pass |
| top14 + tilt25 | 36.62% | -24.79% | 1.317 | pass |

`tilt20` is the conservative first passing arm and is used for the final
candidate. `tilt25` is kept as an adjacent sanity check, not selected.

## Final Broker Results

| Portfolio | CAGR | MaxDD | Sharpe | Avg Cash | Trade Count | Verdict |
|---|---:|---:|---:|---:|---:|---|
| Main | 36.33% | -24.91% | 1.312 | 29.31% | 1573 | pass |
| Concentrated | 52.14% | -23.12% | 1.583 | 42.59% | 684 | pass |

Window checks:

- Main years: `7.0719`
- Concentrated years: `7.0719`
- both end at `2026-06-29`
- both skip the `2026-06-29` signal whose next-close fill would fall after the
  official replay end
- both report `production_activation_allowed=false`

## Interpretation

This is the first current clean-code policy-path probe in this track where both
sleeves exceed the research targets under the cash-carry accounting contract:

- Main target: `36.33% >= 35%`, `-24.91% >= -25%`
- Concentrated target: `52.14% >= 50%`, `-23.12% >= -25%`

This is still not production evidence and not a fullrun result. It is a
pre-fullrun research candidate.

## Remaining Fullrun Blockers

The updated pre-fullrun gate was run against this exact combo:

- output: `outputs/prefullrun_gate_policy_combo_20260704/summary.json`
- status: `blocked`
- policy combo: `research_pass_policy_path_combo`

The strategic/replay blockers are cleared for this frozen candidate. Remaining
hard blockers are mechanical:

1. Cash-carry is still a research accounting contract unless explicitly adopted.
2. Local price/data readiness is missing/stale.
3. Local universe health is invalid because the expected scored/candidate files
   are missing in the current readiness output.
4. `pit_universe_label_clean=false` remains a hard production blocker.
5. A fullrun, if approved later, should be one run only and should use this
   exact frozen hook payload.

## Frozen Candidate Payload

Use this exact payload for the next readiness check:

```json
{
  "PHASE_MAIN_POST_SELECTION_TOPN_FILTER_ENABLED": "1",
  "R1000_MAIN_POST_SELECTION_TOP_N": "14",
  "PHASE_AI_CAPEX_MOMENTUM_TILT_ENABLED": "1",
  "R1000_MAIN_AI_CAPEX_TILT_STRENGTH": "0.20",
  "PHASE_CONCENTRATED_REPLACEMENT_QUALITY_ENABLED": "1",
  "PHASE_CONCENTRATED_CASHFUNDED_EARLY_ENTRY_ENABLED": "1",
  "R1000_CONC_CASHFUNDED_EARLY_ENTRY_ADD_WEIGHT": "0.058",
  "R1000_CONC_CASHFUNDED_EARLY_ENTRY_MIN_BREAKOUT_QUALITY": "0.50"
}
```

Do not add another alpha hook before the readiness check. The next engineering
step is to refresh data/readiness and verify that this exact frozen payload is
eligible for one clean fullrun.
