# AlphaOps vNext Phase 1 Replay Goal Test - 2026-07-01

## Status

Phase 1 replay-stage test is complete. This is not a production promotion run and not a fullrun.

Reference fullrun artifact:

- GitHub Actions run: `28436307420`
- Local artifact root: `artifacts/fullrun_28436307420/official/outputs`
- Official end date: `2026-06-29`
- Metric mode: `broker_ledger_next_close`
- Standing production blocker: `pit_universe_label_clean=false`

Fresh replay cache:

- Path: `outputs/phase1_replay_goal_test/cache_prices`
- Built with requested end `2026-07-01`
- Actual cache max date: `2026-06-30`
- Replay was clamped to official end `2026-06-29`
- Required target tickers, `SPY`, `QQQ`, and `SH` were present and fresh enough.

## Load-Bearing Fixes Applied

1. `run_broker_ledger_replay.py` now skips target signals whose `next_close` fill would occur after `--replay-end-date`.
   - This fixes the last official target date case: signal `2026-06-29`, next-close fill `2026-06-30`, official window end `2026-06-29`.
   - New metric: `replay_end_skipped_rebalance_count`.

2. `run_broker_ledger_replay.py` now filters target rows with `rebalance_date > --replay-end-date`.
   - This supports fresh-cache replay where target generation may include a newer date than the official artifact window.
   - New metrics: `replay_end_filtered_target_row_count`, `replay_end_filtered_target_date_count`.

3. Added repeatable official-book bull-floor A/B harness:
   - Tool: `tools/run_official_book_bull_floor_broker_ab.py`
   - Test: `tests/official_book_bull_floor_broker_ab_smoke.py`
   - Purpose: apply bull-floor lift only to the already-built official target book, without re-running vNext and without double-applying bear/neutral regime dampening.

Validation:

- `python -m py_compile tools/run_broker_ledger_replay.py tools/run_cash_carry_measurement.py tools/run_lever_sweep.py tools/run_official_book_bull_floor_broker_ab.py`
- `python tools/run_pr_validation.py --only broker_cash_carry_smoke --only cash_carry_measurement_smoke --only bull_floor_overlay_smoke --only official_book_bull_floor_broker_ab_smoke`
- Result: all passed.

## Cash-Carry Measurement

Command output:

- Path: `outputs/phase1_replay_goal_test/cash_carry_measurement`
- Status: `completed`
- Metric mode: `broker_ledger_next_close_cash_carry`
- End date match: `true`
- Rate source: `DGS3MO`
- Rate max available_from: `2026-06-30`
- Cash-carry is research-only and not production-valid.

| Portfolio | Arm | CAGR | MaxDD | Sharpe | Cash interest | Verdict |
|---|---:|---:|---:|---:|---:|---|
| Main | baseline | 34.27% | -24.11% | 1.249 | 0 | Official baseline reproduced |
| Main | cash-carry | 35.11% | -23.99% | 1.273 | $12,328 | Passes headline Main target as research |
| Concentrated | baseline | 47.46% | -24.08% | 1.415 | 0 | Official baseline reproduced |
| Concentrated | cash-carry | 48.83% | -23.79% | 1.445 | $22,383 | Improves, but still below 50% CAGR |

Cash-carry deltas:

- Main: `+0.84pp CAGR`, `+0.12pp MaxDD`
- Concentrated: `+1.37pp CAGR`, `+0.28pp MaxDD`

Interpretation:

- Cash-carry is a real replay-stage improvement and solves the Main headline gap under research accounting.
- It does not solve the Concentrated CAGR gap. Remaining gap is about `1.17pp` after cash-carry.
- Because cash-carry is research-only, this does not create production eligibility.

## Bull-Floor Measurement

Two approaches were checked:

1. `run_lever_sweep.py` was rejected for this Phase 1 decision because its floor `0.0` control did not reproduce the official artifact target book.
   - Even with integration env flags, the regenerated vNext concentrated book differed from the official artifact on names and weights.
   - This means the sweep path measures a different target-book generator, not the official baseline.

2. `run_official_book_bull_floor_broker_ab.py` was added and used.
   - It keeps the official target book fixed.
   - It applies only bull-regime cash redeployment to stock exposure.
   - It does not re-run vNext selection.
   - It does not re-apply bear/neutral dampening.

Official-book bull-floor output:

- Path: `outputs/phase1_replay_goal_test/official_book_bull_floor_broker_ab`
- Status: `completed`
- Metric mode: `broker_ledger_next_close_cash_carry`

| Floor | Lifted dates | CAGR | MaxDD | Sharpe | Avg cash | Verdict |
|---:|---:|---:|---:|---:|---:|---|
| 0.00 | 0 | 48.83% | -23.79% | 1.445 | 40.23% | Control |
| 0.85 | 11 | 45.83% | -32.03% | 1.355 | 37.25% | Reject |
| 0.90 | 13 | 45.22% | -33.53% | 1.334 | 36.53% | Reject |
| 0.95 | 16 | 44.71% | -34.90% | 1.315 | 35.73% | Reject |

Interpretation:

- Bull-floor is not a no-op; it fires on 11 to 16 rebalance dates.
- It reduces cash, but the redeployed exposure is harmful in broker replay.
- It fails both Concentrated CAGR and MDD objectives.
- Do not proceed to fullrun based on bull-floor.

## Goal Assessment

Research headline after cash-carry only:

- Main: `35.11% CAGR / -23.99% MDD` - headline pass, research-only.
- Concentrated: `48.83% CAGR / -23.79% MDD` - MDD pass, CAGR short by about `1.17pp`.

Research headline after bull-floor:

- All tested floors make Concentrated worse.
- Bull-floor should be discarded for this official-book path.

Production status:

- `production_activation_allowed=false`
- `pit_universe_label_clean=false` remains a production blocker.
- No live trading, no production mutation, no fullrun justified by this result.

## Next Engineering Steps

1. Commit and push the replay clamp fixes and official-book bull-floor A/B harness.

2. Mark bull-floor as negative evidence for the official artifact path.
   - It is useful as a tested dead end, not as a candidate.

3. Focus the next Concentrated CAGR work on selection/sizing/hold-duration rather than broad cash redeployment.
   - The remaining research gap is about `1.17pp` after cash-carry.
   - The failure mode says extra gross in bull regimes is too blunt.
   - Candidate next tracks:
     - narrower AI-capex / earnings-confirmed leader hold extension,
     - concentrated sizing that preserves the known winner set without broad cash floor,
     - targeted replacement/entry timing where applied-count and broker deltas prove non-no-op.

4. If a future replay-stage lever passes locally, run one fullrun only after:
   - target-book control reproduces the official artifact,
   - metric mode remains broker ledger or explicitly research cash-carry,
   - official end clamp is true,
   - no future `available_from` leakage,
   - `pit_universe_label_clean=false` remains clearly labeled as production blocker.

## Claude / GPT Pro Questions

1. Is the replay-end clamp behavior now conceptually correct?
   - It skips next-close fills after official end.
   - It filters future target rows after official end.

2. Should cash-carry be treated as a research accounting improvement only, or should the project define a production cash-interest accounting contract?

3. Given bull-floor worsens Concentrated despite reducing cash, should the next 1.17pp CAGR gap be attacked via hold-duration/sizing rather than gross-floor exposure?

4. Do you agree that no fullrun is justified until a new lever passes official-book or broker replay control reproduction?

