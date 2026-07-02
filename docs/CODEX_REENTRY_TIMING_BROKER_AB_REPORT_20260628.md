# Re-Entry Timing Broker A/B Report — 2026-06-28

## Verdict

`reclaim_5pct` / `reclaim_10pct` re-entry timing is a real research lever, but it is not a production or fullrun promotion result.

Best research candidate:

- `reclaim5_w01`: +1.38pp CAGR, +0.12pp MaxDD improvement, +0.037 Sharpe, 95 applications.

Most defensive candidate:

- `reclaim10_w02`: +0.73pp CAGR, +0.20pp MaxDD improvement, +0.015 Sharpe, 78 applications.

Rejected high-gross candidate:

- `reclaim5_w05`: reaches 50.53% CAGR, but worsens MaxDD to -26.52%; reject under the 50% CAGR / -25% MDD mission gate.

The conclusion is not "ship". The conclusion is: implement only a default-off hook candidate for cheap target-book and broker A/B review, with `reclaim5_w01` as the primary balanced arm and `reclaim10_w02` as the defensive comparator. No fullrun, production mutation, or live trading follows from this report.

## Baseline

Source artifact:

- `artifacts/28074476465/outputs`
- Target book: `artifacts/28074476465/outputs/alphaops_vnext/official_concentrated_target_book.csv`
- Trades: `artifacts/28074476465/outputs/broker_replay/concentrated/trades.csv`
- Price cache: `artifacts/28074476465/cache_prices`

Exact harness baseline:

| Metric | Value |
|---|---:|
| CAGR | 47.20% |
| MaxDD | -25.82% |
| Sharpe | 1.440 |
| Years | 7.061 |
| Avg cash | 42.14% |
| Trades | 602 |

This exact replay ends on 2026-06-25, so it differs slightly from the official account-evaluation snapshot. A/B decisions in this report use within-harness deltas only.

## No-Lookahead Design

The trigger screen uses all sell events, then fires only from price paths observable after each sell.

Allowed live/PIT trigger inputs:

- sell date
- sell fill price
- post-sell close path up to the trigger date
- ticker MA200 state on the trigger date
- optional market MA200 state on the trigger date

Audit-only fields:

- later actual rebuy price
- forward 20d/63d return
- saved premium vs later actual rebuy

The trigger tool reports `forward_columns_used_for_trigger=false`.

## A/B Harness

Tool:

- `tools/run_reentry_timing_broker_ab.py`

Core mechanics:

- Uses the concentrated target book directly.
- Injects small, cash-funded re-entry rows on trigger dates.
- Preserves official monthly target dates.
- Resets injected re-entry names on each official target rebalance.
- Uses `run_broker_ledger_replay.py` with `broker_ledger_next_close`, integer shares, 25 bps cost, and max fill lag 7.
- Disables legacy concentrated champion filtering so the generated research target book is consumed exactly.
- Emits `summary.json`, `arm_metrics.csv`, `report.md`, generated target books, applied re-entry logs, and broker replay outputs.

## Results

### Initial Arms

| Arm | Applied | CAGR | MaxDD | Sharpe | Delta CAGR pp | Delta MaxDD pp | Verdict |
|---|---:|---:|---:|---:|---:|---:|---|
| baseline | 0 | 47.20% | -25.82% | 1.440 | 0.00 | 0.00 | baseline |
| reclaim5_w03 | 95 | 49.43% | -26.10% | 1.485 | +2.23 | -0.28 | reject_mdd_worse |
| reclaim5_w05 | 89 | 50.53% | -26.52% | 1.495 | +3.34 | -0.70 | reject_mdd_worse |

### Conservative Sweep

| Arm | Applied | CAGR | MaxDD | Sharpe | Delta CAGR pp | Delta MaxDD pp | Verdict |
|---|---:|---:|---:|---:|---:|---:|---|
| reclaim5_w01 | 95 | 48.57% | -25.70% | 1.477 | +1.38 | +0.12 | research_pass_candidate |
| reclaim5_w02 | 95 | 48.98% | -25.89% | 1.481 | +1.79 | -0.07 | reject_mdd_worse |
| reclaim10_w02 | 78 | 47.92% | -25.61% | 1.454 | +0.73 | +0.20 | research_pass_candidate |
| reclaim10_w03 | 78 | 48.06% | -25.81% | 1.453 | +0.86 | +0.01 | research_pass_candidate |
| reclaim10_w05 | 73 | 48.73% | -26.24% | 1.454 | +1.54 | -0.42 | reject_mdd_worse |

### Market-Filtered Sweep

Adding a SPY > MA200 gate did not improve the risk trade-off.

| Arm | Applied | CAGR | MaxDD | Sharpe | Delta CAGR pp | Delta MaxDD pp | Verdict |
|---|---:|---:|---:|---:|---:|---:|---|
| reclaim5_w01_spy | 76 | 48.46% | -26.03% | 1.478 | +1.27 | -0.21 | reject_mdd_worse |
| reclaim5_w02_spy | 76 | 48.84% | -26.47% | 1.481 | +1.64 | -0.65 | reject_mdd_worse |
| reclaim10_w02_spy | 67 | 47.95% | -25.70% | 1.456 | +0.76 | +0.12 | research_pass_candidate |
| reclaim10_w03_spy | 67 | 48.10% | -25.93% | 1.454 | +0.90 | -0.11 | reject_mdd_worse |
| reclaim10_w05_spy | 62 | 48.83% | -26.38% | 1.457 | +1.64 | -0.56 | reject_mdd_worse |

## Interpretation

The user's qualitative diagnosis is supported: the strategy often selects strong leaders, sells them, then pays a higher price to re-enter. Re-entry timing can recover part of that lost compounding.

However:

- Larger re-entry weights push the portfolio over the MDD target.
- The best balanced arm improves both CAGR and MDD but does not close the absolute mission gap.
- The SPY MA200 filter is not a reliable fix here; it reduces applications and often worsens MaxDD in this setup.

Therefore the next hook should be small and conservative:

1. `reclaim5_w01` as the primary balanced variant.
2. `reclaim10_w02` as the defensive comparator.
3. Keep `reclaim5_w05` out of policy despite its 50% CAGR, because it fails MDD.

## Next Work

Implement a default-off research hook only if the next PR keeps these rules:

- Default OFF.
- Concentrated only.
- No target mutation unless env enabled.
- Trigger uses only sell price, post-sell PIT close path, ticker MA200, and optional market state.
- Re-entry is cash-funded and capped at 1%-2% per name.
- Preserve monthly official rebalance reset.
- Telemetry must emit `reentry_trigger`, `reentry_weight`, `cash_after`, `trigger_date`, and `skip_reason`.
- Broker A/B must remain the acceptance layer.

Do not dispatch a fullrun from this result. The correct next step is a default-off hook PR plus another cheap broker A/B.

Production remains blocked while `pit_universe_label_clean=false`.
