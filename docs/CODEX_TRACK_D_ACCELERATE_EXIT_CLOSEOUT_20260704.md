# Track D Accelerate Exit Closeout — 2026-07-04

## Verdict

`screen_reject_no_applied_events`

The state-triggered `accelerate_exit_if_deteriorating` arm remains a no-op after rerunning on the latest 286 book with cash-carry and the locally valid replay window.

## Setup

- Tool: `tools/run_fixed_book_hold_exit_timing_ab.py`
- Target book: `artifacts/run_28616190134_download/user-operating-minimal-global_alpha_universe-28616190134/outputs/reports/operating_concentrated_target_book.csv`
- Price cache: `outputs/p4_cap_replacement_broker_counterfactual_28616190134/cache_prices`
- Output: `outputs/track_d_accelerate_exit_28616190134_replay_end_20260701/`
- Arms: `baseline_cash_carry`, `accelerate_exit_if_deteriorating`
- Replay end: `2026-07-01`
- Cash-carry mode: `risk_free_rate`
- Fullrun executed: `false`
- Production activation allowed: `false`

## Results

| Arm | Applied | CAGR | MaxDD | Sharpe | ΔCAGR | ΔMDD |
|---|---:|---:|---:|---:|---:|---:|
| `baseline_cash_carry` | 0 | 47.79% | -23.02% | 1.426 | 0.00pp | 0.00pp |
| `accelerate_exit_if_deteriorating` | 0 | 47.79% | -23.02% | 1.426 | 0.00pp | 0.00pp |

## Interpretation

- The predicate still has no application events on the latest fixed book.
- Because `applied_count=0`, there is no performance evidence and no reason to build a policy hook.
- Do not dispatch a fullrun from Track D.

## Next

1. Keep Concentrated event-matched replacement quality as the only live performance candidate.
2. Treat state-triggered mid-month exit acceleration as parked until a separate applied-event audit finds real events.
3. Continue infrastructure tracks: W1 control reproduction, cash-carry native emission, and PIT membership.

