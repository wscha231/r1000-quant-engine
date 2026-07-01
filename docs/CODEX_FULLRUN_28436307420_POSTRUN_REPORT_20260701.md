# AlphaOps vNext Fullrun 28436307420 Post-Run Report

Purpose: Claude / GPT Pro review packet. This report analyzes GitHub Actions run 28436307420 after artifact recovery. It is not a production promotion memo.

## 1. Run Facts

- Run: https://github.com/wscha231/r1000-quant-engine/actions/runs/28436307420
- Job: https://github.com/wscha231/r1000-quant-engine/actions/runs/28436307420/job/84262993442
- Branch: `codex/integration-fullrun-clean-20260630`
- Head SHA: `2f83cc815a22c70a1c6322e74fb8afe20d1687da`
- Workflow conclusion: `cancelled`
- Job note: the full rebuild ran long enough to emit official broker and user operating artifacts. The final job was cancelled after the runner hit the 5h50m limit / post-processing window.
- Local artifacts:
  - `H:\codex\tmp_r1000_grossfloor_20260625\artifacts\fullrun_28436307420\official`
  - `H:\codex\tmp_r1000_grossfloor_20260625\artifacts\fullrun_28436307420\user`
  - `H:\codex\tmp_r1000_grossfloor_20260625\artifacts\run_28436307420_logs\full_job.log`

## 2. Official Broker-Ledger Results

Source: `outputs/account_evaluation/official_metrics.json`

| Portfolio | CAGR | MaxDD | Sharpe | Window | Years | Calendar TD | Observed TD | Avg Cash | Latest Cash |
|---|---:|---:|---:|---|---:|---:|---:|---:|---:|
| Main | 34.27% | -24.11% | 1.249 | valid_7y | 7.072 | 1782 | 1778 | 27.09% | 15.66% |
| Concentrated | 47.46% | -24.08% | 1.414 | valid_7y | 7.072 | 1782 | 1778 | 40.21% | 6.15% |

Metric mode is `broker_ledger_next_close`.

Interpretation:

- The 7Y window is now valid: broker start `2019-06-03`, end `2026-06-29`.
- Main MDD is repaired versus prior -26% region, but canonical Main CAGR 35% is still short by about 0.73pp.
- Concentrated MDD is repaired, but canonical Concentrated CAGR 50% is still short by about 2.54pp.
- Both portfolios still fail strengthened robustness mainly through low IS CAGR and high OOS/IS ratio.
- `pit_universe_label_clean=false` remains a hard production blocker.
- `production_promotion_allowed=false`, `production_target_pass=false`, `strengthened_pass=false`.

## 3. SH Hedge Evidence

Source: `outputs/alphaops_vnext/summary.json`, `outputs/latest_price_date_audit.json`, broker account state.

Observed:

- `main_fast_crash_hedge.hedge_ticker = SH`
- `main_fast_crash_hedge.hedge_dates = 2`
- `main_fast_crash_hedge.max_hedge_weight = 7.5%`
- `main_fast_crash_hedge.avg_hedge_weight = 0.176%`
- Latest price audit has `SH = 2026-06-30`

Interpretation:

- The previous SH collection blocker is resolved for this run.
- The hedge path is not a no-op. It fired on two dates.
- Main MDD improvement is consistent with the hedge being active, but final acceptance still needs apples-to-apples delta reporting against the immediately previous baseline.

## 4. Current Simulated Broker-Ledger Holdings

Source: `outputs/user_current/01_current_holdings.csv`

Important: these are simulated broker-ledger holdings, not live account holdings.

### Main

| Ticker | Weight |
|---|---:|
| SNDK | 16.59% |
| CASH | 15.66% |
| WDC | 13.31% |
| MRVL | 11.51% |
| STM | 11.40% |
| CIEN | 6.62% |
| MU | 5.27% |
| LITE | 4.45% |
| PWR | 4.00% |
| ON | 3.88% |
| FIX | 2.67% |
| COHR | 2.39% |
| TER | 1.50% |
| KEYS | 0.76% |

### Concentrated

| Ticker | Weight |
|---|---:|
| SNDK | 39.19% |
| BE | 21.48% |
| WDC | 20.03% |
| CIEN | 8.57% |
| CASH | 6.15% |
| LITE | 4.59% |

## 5. User Current Target / Order State

Source: `outputs/user_current/02_target_weights.csv`, `08_rebalance_decision.json`

Top target snapshot:

- Main target has 40.00% cash and new target names such as `VRT`, `GOOG`, `GEV`, `NVDA`, `CAT`, `UMC`, `AMAT`, `AMD`, `LRCX`.
- Concentrated target is `AMD 38.46%`, `AMAT 34.19%`, `GLW 27.35%`, `CASH 0%`.
- Rebalance decision is `REVIEW_REQUIRED`.
- `review_only=true`, `live_trading_enabled=false`, `production_mutation_allowed=false`, `human_approval_required=true`, `promotion_allowed=false`.
- Estimated turnover is about 358%.

Interpretation:

- This is not a trade instruction.
- Target snapshot has very high turnover and differs materially from current simulated holdings.
- The user-facing target contract and account-ledger preview contract need reconciliation before another official run.

## 6. Why The Workflow Failed / Cancelled

The strategy broker metrics were produced and are usable as research evidence. The workflow did not fail because official broker replay was missing.

Primary blocker emitted by `outputs/live_trading_safety/safety_audit_summary.json`:

- `status = blocked`
- `error_count = 2`
- `main_target_missing_price_rows`
- `concentrated_target_missing_price_rows`

Reported missing target rows:

- Main: `AMAT`, `AMD`, `BE`, `CAT`, `DVA`, `GEV`, `GOOG`, `KIM`, `KLAC`, `LRCX`, `NTES`, `NVDA`, `TKR`, `UMC`, `VRT`
- Concentrated: `AMAT`, `AMD`, `GLW`

Key diagnosis:

- `run_live_trading_safety_audit.py` validates `portfolio_latest.csv` / `concentrated_portfolio_latest.csv` target tickers against `account_ledger_preview/*/positions_current.csv`.
- `positions_current.csv` only contains current simulated broker holdings.
- The user-facing canonical target contains new target-only names.
- Therefore the safety audit treats valid target-only tickers as "missing price rows".
- This is an output contract bug / safety audit contract bug, not a strategy alpha failure.

Secondary issue:

- `outputs/account_ledger_preview/*/target_weights.csv` does not match `outputs/user_current/02_target_weights.csv`.
- Example: concentrated account preview target remains `BE/SNDK/WDC/CIEN/CASH/LITE`, while user current target is `AMD/AMAT/GLW/CASH`.
- The next fix must reconcile which target snapshot is canonical for safety audit, user_current, and order preview.

## 7. Data Freshness / PIT Status

Source: `outputs/daily_market_snapshot/summary.json`, `outputs/latest_price_date_audit.json`

- Snapshot as-of date: `2026-06-30`
- Latest price max: `2026-06-30`
- Latest price min: `2026-06-26`
- Price available count: 530
- Selection usable count: 504
- Stale price rows > 3d: 1
- Latest price date audit status: `ok`
- Missing latest price tickers: 0
- `pit_label = latest_operating_snapshot_not_historical_pit`

Production remains blocked by historical membership PIT status.

## 8. Recommended Next Engineering Steps

Do not dispatch another fullrun yet.

1. Fix the safety audit / preview contract:
   - Either ensure `run_account_order_preview.py` emits zero-share price rows for every target-only ticker with valid reference price, or
   - update `run_live_trading_safety_audit.py` so it validates target-only price coverage through `orders_preview.csv`, `projected_positions_after_orders.csv`, or an explicit target price coverage table rather than requiring all target tickers to be in `positions_current.csv`.

2. Reconcile canonical target snapshots:
   - `user_current/02_target_weights.csv`
   - `portfolio_latest.csv`
   - `concentrated_portfolio_latest.csv`
   - `account_ledger_preview/*/target_weights.csv`
   - `account_ledger_preview/*/orders_preview.csv`

3. Add smoke tests:
   - A target-only new buy ticker with valid price must not trigger `*_target_missing_price_rows`.
   - A target-only new buy ticker without valid price must still block.
   - `user_current` target and account-ledger preview target must agree on canonical semantics.

4. Re-run cheap local validation only:
   - live trading safety audit smoke
   - account order preview smoke
   - user_current contract smoke

5. Only after those pass, consider one new fullrun.

## 9. Strategic Interpretation

Positive:

- 7Y window is clean and valid.
- SH hedge is collected and fires.
- Main MDD is repaired to -24.11%.
- Concentrated MDD is also within -25%.

Still unresolved:

- Main canonical CAGR is still below 35%.
- Concentrated canonical CAGR is still below 50%.
- Both portfolios have weak IS CAGR and high OOS/IS ratio.
- `pit_universe_label_clean=false` still blocks production.
- User-facing target/order/safety file contracts are inconsistent.

Priority after contract fix:

1. Do not spend more time on Main MDD unless a new, cheap diagnostic appears. The current hedge path did its job.
2. Focus alpha work on Concentrated CAGR gap.
3. Continue PIT membership track for production evidence.
4. Keep all outputs review-only until human approval.

## 10. Questions For Claude / GPT Pro

1. Do you agree that run 28436307420 produced usable research broker metrics despite workflow conclusion `cancelled`?
2. Do you agree the immediate blocker is a target/preview/safety audit contract bug rather than a strategy failure?
3. Should safety audit require target-only tickers to appear in `positions_current.csv`, or should it use explicit target price coverage / orders preview reference prices?
4. Which file should be canonical for the user-facing target: `user_current/02_target_weights.csv`, `portfolio_latest.csv`, or `account_ledger_preview/*/target_weights.csv`?
5. Is SH hedge evidence sufficient to freeze the Main MDD track for now?
6. Does the Concentrated CAGR gap remain the next alpha priority?
7. Should another fullrun be blocked until the safety contract mismatch is fixed and tested locally?

## 11. 2026-07-01 Follow-Up Implementation

Codex implemented the immediate contract fixes and cash-carry measurement plumbing after this report was first drafted.

Implemented:

- `user_current/02_target_weights.csv` now prefers operating / official target books before falling back to `user_portfolio_reports`.
- Target rows now carry snapshot provenance:
  - `target_snapshot_hash`
  - `target_snapshot_source_path`
  - `target_snapshot_generated_at`
  - `target_snapshot_semantics`
  - `target_snapshot_portfolio`
- `account_ledger_preview/<portfolio>/target_price_coverage.csv` is emitted for every target ticker.
- `run_live_trading_safety_audit.py` validates target-only new buys through `target_price_coverage.csv` instead of requiring them to appear in `positions_current.csv`.
- Missing target-only price still blocks; target-only new buy with a valid reference price no longer false-blocks.
- Cash-carry research accounting from PR #214 was cherry-picked into the integration branch.
- `tools/materialize_cash_rate_series.py` materializes DGS3MO into the local FRED cache convention.
- `tools/run_cash_carry_measurement.py` runs paired baseline vs `broker_ledger_next_close_cash_carry` broker replays without fullrun.

Validation:

- `py_compile` passed for modified tools.
- `tools/run_pr_validation.py` passed for:
  - `account_order_preview_smoke`
  - `live_trading_safety_audit_smoke`
  - `daily_user_current_contract_smoke`
  - `cash_rate_materialization_smoke`
  - `cash_carry_measurement_smoke`
  - `broker_cash_carry_smoke`

Cash-rate materialization:

- DGS3MO cache materialized locally.
- Rows: 11205
- Date range: 1981-09-01 to 2026-06-29
- Latest rate: 3.87%

Cash-carry probe:

- A local cash-carry probe was run against recovered 28436307420 target books.
- Because the recovered 28436307420 artifact did not include full `cache_prices`, the probe used an older local price cache ending 2026-06-22.
- Therefore this is a functional / directional probe, not official final evidence.

Probe result:

| Portfolio | CAGR delta | MaxDD delta | Cash interest accrued |
|---|---:|---:|---:|
| Main | +0.83pp | +0.08pp | $12,166 |
| Concentrated | +1.39pp | +0.28pp | $22,317 |

Interpretation:

- The previous triage estimate that cash-carry can improve both sleeves is directionally supported.
- The no-op guard passed because actual cash interest accrued was positive.
- A final cash-carry measurement should be repeated only when a fresh, full price cache aligned to the official run is available.
- No production promotion follows from this; cash-carry is research-only until explicitly accepted.

## 12. 2026-07-01 Contract Closure Follow-Up

Codex then implemented the remaining high-priority contract closure items before any new fullrun:

- Preserved target snapshot metadata through account preview:
  - `target_snapshot_hash`
  - `target_snapshot_source_path`
  - `target_snapshot_generated_at`
  - `target_snapshot_semantics`
  - `target_snapshot_portfolio`
- Added `tools/verify_user_current_preview_contract.py`.
  - Blocks when user_current and account preview targets differ by ticker, weight, hash, or semantics.
- Strengthened `target_price_coverage.csv`.
  - Adds `price_lag_days` and `max_stale_days`.
  - Emits `missing_price`, `invalid_price`, `future_dated_price`, or `stale_price` rather than treating old prices as ok.
  - Safety audit blocks all non-ok target price statuses.
- Strengthened `tools/run_cash_carry_measurement.py`.
  - Blocks official measurement if the price cache does not cover the official run end date.
  - Blocks official measurement if the rate cache does not cover the replay window.
  - Passes IS/OOS/OOS2 windows into both baseline and cash-carry broker replays.
  - Reports IS/OOS cash-carry deltas and OOS/IS ratios.

Validation:

- `py_compile` passed for modified tools.
- `tools/run_pr_validation.py` passed for:
  - `account_order_preview_smoke`
  - `user_current_preview_contract_smoke`
  - `live_trading_safety_audit_smoke`
  - `cash_carry_measurement_smoke`
  - `cash_rate_materialization_smoke`
  - `broker_cash_carry_smoke`

Important proof:

- Re-running the cash-carry measurement with the older 2026-06-22 price cache now blocks as intended:
  - `status=blocked`
  - `reason=blocked_stale_price_cache_for_cash_carry`
  - `required_end_date=2026-06-29`
  - `price_cache_max_date=2026-06-22`

Interpretation:

- The earlier cash-carry result remains useful as a directional probe.
- The tooling now prevents that older-cache probe from being mistaken for official aligned evidence.
- A new fullrun is still not required before official aligned cash-carry measurement.

## 13. 2026-07-01 Target-Ticker Price Alignment Follow-Up

Claude / GPT Pro review identified one remaining load-bearing gap: cash-carry price-cache alignment could not rely only on `SPY` and `QQQ`. If benchmarks were fresh but actual target tickers were stale, the measurement could look official while replaying stale target prices.

Codex fixed this in `tools/run_cash_carry_measurement.py`:

- Required price tickers now include:
  - all non-CASH tickers present in operating / official target books
  - shared env-required tickers from `tools/alphaops_required_price_tickers.py`
  - `SPY` / `QQQ` benchmark anchors
  - `SH` only when the fast-crash hedge env requires it
- Summary now reports:
  - `target_price_cache_min_date`
  - `target_price_cache_max_date`
  - `target_price_cache_missing_tickers`
  - `target_price_cache_stale_tickers`
  - `target_price_cache_aligned_all_targets`
  - `required_price_tickers_checked`
  - `target_price_tickers_checked`
  - `env_price_tickers_checked`

Validation:

- Added a smoke case where `SPY` / `QQQ` are fresh but target ticker `AAA` is stale.
- The measurement blocks with:
  - `status=blocked`
  - `reason=blocked_stale_price_cache_for_cash_carry`

Artifact re-check:

- Re-running cash-carry measurement against recovered run `28436307420` with the older `2026-06-22` cache now blocks on all-target alignment, not just benchmark alignment.
- Example emitted fields:
  - `required_end_date=2026-06-29`
  - `price_cache_max_date=2026-06-22`
  - `target_price_cache_aligned_all_targets=false`
  - target tickers such as `SNDK`, `WDC`, `BE`, `CIEN`, `AMD`, `AMAT`, and many historical target-book tickers are correctly flagged stale when the cache ends before the official run end date.

Interpretation:

- Official cash-carry measurement now requires fresh actual target ticker prices.
- The old directional probe remains useful for expectation-setting only.
- The next execution step is still not fullrun; it is fresh replay price cache generation followed by official-aligned cash-carry measurement.

## 14. 2026-07-01 Replay End-Date Clamp Follow-Up

Claude / GPT Pro review identified one more official-measurement trap: after a fresh price-cache refresh, `run_broker_ledger_replay.py` could extend the final target period to the cache's newest bar. That would make cash-carry / bull-floor replay run beyond official run `28436307420`'s broker end date (`2026-06-29`) and break apples-to-apples comparison.

Codex fixed this in `tools/run_broker_ledger_replay.py`:

- Added `--replay-end-date`.
- Added `--official-baseline-end-date`.
- The final target period now clamps to `min(price_cache_latest, replay_end_date)`.
- If `replay_end_date` is earlier than the target book's last rebalance date, replay blocks.
- If a requested `replay_end_date` is not actually present in the replay equity curve, replay blocks with `replay_end_date_not_observed`.
- Metrics now report:
  - `requested_replay_end_date`
  - `actual_equity_curve_end_date`
  - `replay_end_date_clamped`
  - `official_baseline_end_date`
  - `end_date_matches_official`

Pass-throughs:

- `tools/run_cash_carry_measurement.py` now passes the official end date into both baseline and cash-carry broker replay arms.
- `tools/run_lever_sweep.py` accepts `--replay-end-date` and passes it to the concentrated gross / bull-floor broker replay command.

Validation:

- Added a broker smoke where price cache contains bars after the official end date but `replay_end_date=2026-01-06`; the equity curve ends exactly at `2026-01-06`, not at the cache max date.
- Cash-carry measurement smoke now requires `end_date_matches_official=true`.
- `run_lever_sweep.py --dry-run --replay-end-date 2026-06-29` shows the broker command includes both `--replay-end-date 2026-06-29` and `--official-baseline-end-date 2026-06-29`.
- Re-running recovered run `28436307420` cash-carry measurement against the stale 2026-06-22 cache still blocks with `blocked_stale_price_cache_for_cash_carry`, now with explicit `requested_replay_end_date=2026-06-29`.

Interpretation:

- Official-aligned replay-stage measurement now has both required guards:
  - all actual target/env ticker prices must be fresh through the official end date
  - replay must not extend past the official end date even if the cache contains later bars
- Fullrun is still not the next step. The next step is fresh replay price cache generation, then official-aligned cash-carry measurement with `--replay-end-date 2026-06-29`.
