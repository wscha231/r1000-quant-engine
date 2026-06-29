# Whipsaw Sell-Throttle Candidate Result - 2026-06-29

## Summary

This document records the first default-OFF policy candidate derived from PR
#203's whipsaw cost and PIT feature screens.

Verdict: `reject_for_concentrated_cagr_goal`, but preserve as a possible
research-only risk reducer.

The hook fired and improved drawdown, but it did not improve the active
Concentrated CAGR objective.

## Candidate

Hook:

- `PHASE_CONCENTRATED_WHIPSAW_SELL_THROTTLE_ENABLED`

Scope:

- Concentrated only.
- Default OFF.
- No production mutation.
- No live trading.
- No fullrun.
- No ticker, date, sector, or theme hardcoding.

Mechanism:

- Runs after selected names are weighted and after existing concentrated risk
  caps.
- Does not re-add dropped names.
- Does not alter candidate ranking or replacement thresholds.
- Applies only to existing prior holdings with sell-time PIT thesis integrity:
  - `holding_state == HOLD`
  - `hold_replace_decision == keep_prior_holding`
  - `leader_tier in {DUAL_LEADER, SECTOR_LEADER}`
  - `rs_benchmark_3m > 0`
  - `rs_benchmark_6m > 0`
  - `price_above_ma200 >= 0.5`
  - `actual_results_score > 0`
  - no hard reject
  - not CRISIS/DEFENSE
- Limits the monthly reduction by lifting the current weight toward 75% of
  prior weight, capped at 8pp per name per month.
- Preserves stock gross by funding protected-name lifts from other stock rows
  pro-rata; cash is not used as the funding source.

## Cheap Target-Book Screen

Inputs:

- latest run: `artifacts/28074476465/outputs`
- baseline output: `artifacts/28074476465/whipsaw_sell_throttle_off_20260629`
- hook output: `artifacts/28074476465/whipsaw_sell_throttle_on_20260629`

Result:

- rows off/on: 503 / 503
- changed rows: 230
- changed rebalance dates: 46
- total absolute target-weight delta: 6.6452
- applied rows: 61
- applied rebalance dates: 46
- max absolute total weight delta by date: effectively 0

Status counts in hook target book:

| Status | Count |
|---|---:|
| funding_source | 168 |
| not_candidate | 160 |
| applied | 61 |
| not_needed | 30 |

Interpretation:

- This was not a no-op.
- The hook materially changed the target book.
- The changes are broad enough that broker-ledger A/B was justified.

## Broker-Ledger A/B

Replay settings:

- `broker_ledger_next_close`
- integer shares
- 25 bps costs
- max fill lag 7
- concentrated champion filter disabled
- OOS start: `2024-06-03`
- OOS2 start: `2023-06-03`

| Arm | CAGR | MDD | Sharpe | OOS CAGR | OOS MDD | Trades | Fees |
|---|---:|---:|---:|---:|---:|---:|---:|
| baseline | 46.14% | -28.37% | 1.271 | 112.93% | -28.37% | 577 | $48.0k |
| whipsaw sell-throttle | 45.84% | -26.32% | 1.284 | 113.04% | -26.32% | 575 | $43.1k |

Delta:

- CAGR: -0.304pp
- MDD: +2.051pp
- Sharpe: +0.013
- OOS CAGR: +0.113pp
- OOS MDD: +2.051pp
- OOS2 CAGR: +0.148pp
- OOS2 MDD: +2.051pp
- trade count: -2
- fees: -$4.9k
- gross traded: -$1.96m

## Interpretation

The hook does what it was designed to do mechanically:

- it fires (`applied_count > 0`);
- it reduces churn and fees;
- it improves MDD materially;
- it preserves the target-book evidence chain and broker-ledger measurement.

But it fails the active objective:

- Concentrated needs CAGR improvement toward 50%;
- this hook lowers full-period CAGR from 46.14% to 45.84%.

The result is consistent with the prior failed actual-results hold hook:
preventing sell pressure can reduce risk and churn, but it can also block
useful rotation enough to reduce full-period CAGR.

## Decision

Do not promote this hook as the next Concentrated CAGR lever.

Classification:

- `reject_for_concentrated_cagr_goal`
- `park_as_risk_reducer_candidate`

It can be reconsidered only if governance prioritizes drawdown/turnover
reduction over Concentrated CAGR.

## Next Direction

For the active CAGR goal, continue searching for mechanisms that increase
winner exposure without suppressing useful rotation.  Candidates should target:

- stronger sizing of already-selected winners when the signal is current and
  PIT-visible;
- earlier re-entry after a valid same-name buy signal;
- better distinction between constructive partial trim and harmful whipsaw.

Do not run a fullrun from this hook.
