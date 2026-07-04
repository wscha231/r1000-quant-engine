# AlphaOps Clean-Control Replay Status - 2026-07-04

## Purpose

This note records the next local step after the pre-fullrun gate. The dirty
official artifact from run `28436307420` is not exactly reproducible from the
current clean branch, but same-machine reproduction of current clean code is
exact. Therefore, before any new fullrun, we measured the current clean target
books directly with broker replay.

No fullrun was dispatched. No production or live state was changed.

## Inputs

Clean control target books:

- `outputs/target_book_control_repro_root_cause/repro_a/official_main_target_book.csv`
- `outputs/target_book_control_repro_root_cause/repro_a/official_concentrated_target_book.csv`

Price/rate data:

- price cache: `outputs/phase1_replay_goal_test/cache_prices`
- cash rate: `cache_macro/fred_dgs3mo_DGS3MO.parquet`
- replay end: `2026-06-29`
- fill mode: `next_close`
- cost: `25 bps`
- integer shares: default broker replay

Outputs:

- `outputs/clean_control_broker_replay/main_zero_yield/metrics.json`
- `outputs/clean_control_broker_replay/main_cash_carry/metrics.json`
- `outputs/clean_control_broker_replay/concentrated_zero_yield/metrics.json`
- `outputs/clean_control_broker_replay/concentrated_cash_carry/metrics.json`
- `outputs/clean_control_replacement_counterfactual/concentrated_cash_carry_full_missed/summary.json`

## Clean-Control Broker Metrics

| Portfolio | Accounting | CAGR | MaxDD | Verdict |
|---|---:|---:|---:|---|
| Main | zero-yield | 35.19% | -25.81% | CAGR pass, MDD fail |
| Main | cash-carry | 36.06% | -25.81% | CAGR pass, MDD fail |
| Concentrated | zero-yield | 45.81% | -27.31% | fail |
| Concentrated | cash-carry | 47.30% | -25.06% | near, but fail |

Interpretation:

- Current clean code is not fullrun-ready even with cash-carry.
- Main's current blocker is MDD, not CAGR.
- Concentrated remains short on CAGR and is slightly below the MDD bar.
- The prior dirty-official reference cannot be used as a clean current-code
  acceptance baseline.

## Replacement-Quality Recheck on Clean Control

Frozen rule:

- `rank_top15_and_revenue_ge10`
- input: full `missed_leaders_audit.csv`
- fixed-book / research-only
- cash/exposure preserved
- forward labels audit-only

Result:

| Metric | Baseline | Challenger | Delta |
|---|---:|---:|---:|
| CAGR | 47.30% | 48.75% | +1.45pp |
| MaxDD | -25.06% | -25.08% | -0.02pp |
| Sharpe | 1.422 | 1.467 | +0.044 |
| IS CAGR delta | | | +0.13pp |
| OOS CAGR delta | | | +7.67pp |
| Swap count | | 17 | |

Concentration guard:

- top added ticker share: 17.65%
- top era share: 47.06%
- top year share: 29.41%
- no concentration block
- no broad cash reduction
- no cap breach

Interpretation:

- Replacement-quality remains a real positive replay-stage candidate.
- It is not enough by itself on the current clean control book.
- It does not justify a fullrun yet.
- It should remain a candidate component, not a standalone acceptance claim.

## Updated Fullrun Gate

Still blocked.

Reasons:

1. price readiness is missing/stale locally;
2. old dirty official artifact is not exact-reproducible under current clean code;
3. current clean control fails mission gates;
4. replacement-quality improves Concentrated but does not reach 50% / -25%;
5. Main clean control fails MDD;
6. earnings/guidance feed is still `DATA_INSUFFICIENT`;
7. universe health is still invalid / PIT-clean is false.

## Next Engineering Order

1. Keep `rank_top15_and_revenue_ge10` frozen as the replacement-quality
   candidate, but do not promote it alone.
2. Solve Main MDD on the clean control book, or formally record that current
   long-only clean code needs another risk component.
3. Find the remaining Concentrated +1.25pp to +2.7pp without gross-floor or
   broad cash reduction.
4. Refresh price readiness only after a candidate combination can plausibly
   pass.
5. Create one clean official control artifact only after the above is true.

## Claude/GPT Pro Routing

No immediate review is required. If a review is requested, send this question:

> On current clean-control broker replay, Main cash-carry is 36.06% / -25.81%,
> Concentrated cash-carry is 47.30% / -25.06%, and frozen replacement-quality
> improves Concentrated to 48.75% / -25.08% without concentration or cash/gross
> violations. Do you agree that fullrun remains blocked, and that the next work
> should be a small clean-control combination search for Main MDD and the
> remaining Concentrated CAGR gap, rather than another review of the already
> falsified dirty official artifact?

Expected answer should be yes unless a new blocker is identified.
