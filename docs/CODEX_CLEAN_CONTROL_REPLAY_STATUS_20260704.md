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

## Main Fixed-Book Candidate

Main now has a separate fixed-book research pass candidate:

- Base repair: `top14` concentration boundary
- Add-on: AI bottleneck momentum tilt15
- Output: `outputs/clean_control_main_top14_ai_capex_tilt/main/`

| Arm | CAGR | MaxDD | Sharpe | Verdict |
|---|---:|---:|---:|---|
| top14 baseline | 34.77% | -24.86% | 1.274 | `baseline` |
| top14 + AI bottleneck momentum tilt15 | 35.36% | -24.76% | 1.283 | `research_pass_policy_candidate` |
| top14 + AI bottleneck momentum + earnings tilt15 | 34.84% | -24.77% | 1.274 | `research_edge_too_small` |

Interpretation:

- Main has a fixed-book research candidate under the cash-carry accounting
  contract.
- This is still not production evidence.
- The `top14` boundary must be reproduced by policy-path or explicitly
  implemented as a default-off research lever before fullrun acceptance.

## Concentrated Fixed-Book Combination Candidate

Concentrated now has a fixed-book combination candidate:

- Component 1: event-matched replacement-quality
- Component 2: non-sticky cash-funded early entry, `entry_w5p8`
- Output: `outputs/clean_control_concentrated_replacement_cashfunded_early_entry_ab/`

| Arm | CAGR | MaxDD | Sharpe | Applied | Verdict |
|---|---:|---:|---:|---:|---|
| replacement-quality baseline | 48.75% | -25.08% | 1.467 | 0 | `baseline` |
| replacement-quality + entry_w3p0 | 49.98% | -23.53% | 1.484 | 43 | `partial` |
| replacement-quality + entry_w5p8 | 51.04% | -23.93% | 1.498 | 43 | `research_pass_policy_candidate` |
| replacement-quality + entry_w3p0_breakout70 | 49.18% | -24.80% | 1.474 | 9 | `partial` |
| replacement-quality + entry_w5p8_breakout70 | 49.60% | -24.53% | 1.481 | 9 | `partial` |

Interpretation:

- Early entry alone is not safe: official-book `entry_w5p8` reaches 50.15%
  CAGR but worsens MaxDD to -25.48%.
- The pass requires the combined replacement-quality + cash-funded early-entry
  structure.
- Simple count sanity check does not show one-ticker or one-era dependence:
  `43` applied dates, top ticker by count `NVDA` with `3`, and applied dates
  spread across `2019`, `2020`, `2021`, `2023`, `2024`, `2025`, and `2026`.

## Updated Fullrun Gate

Improved, but still blocked.

Reasons:

1. price readiness is missing/stale locally;
2. old dirty official artifact is not exact-reproducible under current clean code;
3. fixed-book candidates now pass both sleeves, but policy-path reproduction is
   not yet proven;
4. regenerated selection-side A/B remains diagnostic until W1 control
   reproduction is resolved;
5. earnings/guidance feed is still `DATA_INSUFFICIENT`;
6. universe health is still invalid / PIT-clean is false.

## Next Engineering Order

1. Keep `rank_top15_and_revenue_ge10` frozen as the replacement-quality
   candidate.
2. Keep `entry_w5p8` frozen as the cash-funded early-entry candidate when
   paired with replacement-quality; do not use it alone as a policy candidate.
3. Map fixed-book transformations to policy-path hooks and verify applied
   counts / target-book deltas before any fullrun.
4. Refresh price readiness only after the policy-path hooks reproduce the
   fixed-book candidate behavior.
5. Create one clean official control artifact only after the above is true.

## Claude/GPT Pro Routing

No immediate review is required. If a review is requested, send this question:

> On current clean-control broker replay, fixed-book Main top14 + AI bottleneck
> momentum reaches 35.36% / -24.76%, and fixed-book Concentrated
> replacement-quality + cash-funded early entry reaches 51.04% / -23.93%.
> Do you agree that the next step is policy-path reproduction and data
> readiness, not more fixed-book alpha search or a premature fullrun?

Expected answer should be yes unless a new blocker is identified.
