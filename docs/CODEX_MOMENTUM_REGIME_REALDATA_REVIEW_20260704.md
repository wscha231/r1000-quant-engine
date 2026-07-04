# CODEX Momentum / Regime Real-Data Review - 2026-07-04

## Purpose

This document records the first real-data pass for the M/R research layer after
the midcheck hardening. It is for Claude/GPT Pro review.

This is not a production policy, not a trading signal, and not a fullrun
trigger.

## Code State

Recent relevant commits:

- `9ab0b63b feat: add momentum regime research audits`
- `ae2fd139 docs: refine momentum regime scorecard`
- `fc292693 docs: add momentum regime research tracks`

Additional local hardening performed after the midcheck:

- R1 critical-group coverage and service/public `DATA_INSUFFICIENT` logic.
- R1 price-cache-derived coverage for:
  - SPY realized-volatility stress proxy.
  - Cached-universe breadth above MA200.
  - AI capex basket relative strength vs QQQ.
- R1 macro-cache-derived credit/liquidity coverage for:
  - HY OAS widening.
  - 10Y minus 3M yield-curve inversion/steepening warning.
  - Sahm realtime unemployment momentum.
- R1 earnings/guidance coverage hook:
  - Reads `data_pit/events/earnings_revision_signals.parquet` when present.
  - Uses only rows with `available_from <= as_of_date`.
  - Emits `eps_revision_breadth_negative` and
    `positive_guidance_ratio_deteriorating`.
- W4 raw feed contract:
  - `docs/CODEX_EARNINGS_GUIDANCE_FEED_CONTRACT_20260704.md`
  - `docs/templates/earnings_revisions_template.csv`
  - `tools/validate_earnings_revision_feed.py`
- R1 service/public state override remains disabled unless explicitly allowed.
- R1 output now includes:
  - `state_computed_from_data`
  - `state_override_used`
  - `allow_state_override`
  - `public_display_allowed=false`
  - `review_only=true`
  - `backtest_metrics_are_simulated=true`
  - `current_holdings_are_not_forward_promise=true`
- R1b `DATA_INSUFFICIENT` now emits data-review actions only, with no allocation
  guidance.
- R2 R3-authorization now requires sample, era, state-month, and OOS/sign
  stability gates, not just a large IC gap.
- M1/M2 summaries mark regenerated target-book acceptance as disallowed until
  W1 control reproduction is solved.

## Validation

Runtime:

`C:\codex-shadow\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe`

Targeted validation:

```powershell
C:\codex-shadow\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -B tools\run_pr_validation.py `
  --only momentum_beta_decomposition_smoke `
  --only rs_horizon_ic_audit_smoke `
  --only regime_nowcast_dial_smoke `
  --only regime_nowcast_data_insufficient_critical_group_smoke `
  --only regime_nowcast_price_cache_coverage_smoke `
  --only regime_nowcast_macro_cache_coverage_smoke `
  --only regime_nowcast_earnings_guidance_coverage_smoke `
  --only chameleon_policy_audit_smoke `
  --only chameleon_policy_no_orders_smoke `
  --only chameleon_policy_data_insufficient_no_allocation_smoke `
  --only state_override_service_forbidden_smoke `
  --only state_conditional_ic_audit_smoke `
  --only state_conditional_ic_era_gate_smoke
```

Result:

- 13/13 PASS.

Additional W4 contract validation:

```powershell
C:\codex-shadow\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -B tools\run_pr_validation.py `
  --only earnings_revision_feed_contract_smoke `
  --only earnings_revision_signals_smoke `
  --only regime_nowcast_earnings_guidance_coverage_smoke
```

Result:

- 3/3 PASS.

## Real-Data R1 Run

Command:

```powershell
C:\codex-shadow\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -B tools\run_regime_nowcast_dial.py `
  --price-cache outputs\p4_cap_replacement_broker_counterfactual_28616190134\cache_prices `
  --macro-cache cache_macro `
  --earnings-signals data_pit\events\earnings_revision_signals.parquet `
  --as-of-date 2026-07-01 `
  --coverage-mode service `
  --output-dir outputs\regime_nowcast_dial_realdata_service
```

Inputs:

- Price cache:
  `outputs\p4_cap_replacement_broker_counterfactual_28616190134\cache_prices`
- Manifest end: `2026-07-01`
- Actual cached ticker count: `160`
- Required tickers in that cache include `SPY`, `QQQ`, `AMD`, `MU`, `SNDK`,
  `WDC`, `CIEN`, `LITE`, `BE`, `GLW`, `UMC`, and `AMAT`.
- Macro cache was materialized from FRED graph CSV for:
  - `DGS10`: latest `2026-07-01`, value `4.48`
  - `BAMLH0A0HYM2`: latest `2026-07-01`, value `2.74`
  - `SAHMREALTIME`: latest `2026-06-01`, value `0.07`
  - `UNRATE`: latest `2026-06-01`, value `4.2`
  - `VIXCLS`: latest `2026-07-01`, value `16.59`
- Earnings/guidance feed status:
  - Raw feed contract exists at
    `docs/CODEX_EARNINGS_GUIDANCE_FEED_CONTRACT_20260704.md`.
  - Template header exists at
    `docs/templates/earnings_revisions_template.csv`.
  - Contract validator exists at `tools/validate_earnings_revision_feed.py`.
  - `tools/build_earnings_revision_signals.py --as-of 2026-07-01` emitted
    `status=blocked`, `reason=missing_input`.
  - `tools/validate_earnings_revision_feed.py --as-of 2026-07-01` emitted
    `status=blocked`, `reason=missing_input`.
  - Missing input path:
    `data_raw/events/earnings_revisions.csv`
  - Therefore `data_pit/events/earnings_revision_signals.parquet` does not
    exist yet in this local run.

Materialization command shape:

```powershell
foreach ($s in @('dgs10','hy_oas','sahm','unrate','vix')) {
  C:\codex-shadow\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -B tools\materialize_cash_rate_series.py `
    --rate-source $s `
    --output-cache cache_macro `
    --summary "outputs\regime_macro_materialization_$s\summary.json" `
    --force
}
```

Output paths:

- `outputs/regime_nowcast_dial_realdata_service/summary.json`
- `outputs/regime_nowcast_dial_realdata_service/signal_panel.csv`
- `outputs/regime_nowcast_dial_realdata_service/indicator_rows.csv`
- `outputs/regime_nowcast_dial_realdata_service/state_history.csv`
- `outputs/regime_nowcast_dial_realdata_service/report.md`

Result:

| field | value |
|---|---:|
| status | `completed` |
| current_state | `BULL` |
| bear_warning_score | `0` |
| bear_warning_label | `risk_on` |
| covered_signal_count | `9 / 12` |
| signal_coverage | `0.75` |
| critical_group_coverage | `5 / 6` |
| data_insufficient_reason | empty |
| triggered_signals | `[]` |
| market_timing_claim_allowed | `false` |
| public_display_allowed | `false` |
| policy_hook_allowed | `false` |
| live_trading_allowed | `false` |

Covered groups:

- `trend`: true
- `volatility_stress`: true, via SPY realized-volatility proxy
- `breadth`: true, via fresh price-cache parquet files without ticker mapping
- `ai_bucket_rs`: true, via AI capex basket RS vs QQQ
- `credit_liquidity`: true, via FRED macro cache

Missing critical groups:

- `earnings_guidance`

Missing warning signals:

- `eps_revision_breadth_negative`
- `positive_guidance_ratio_deteriorating`
- `soxx_smh_rs_negative_vs_qqq`

Interpretation:

- R1 can now compute a service-mode state from local price and macro caches.
- The computed state is `BULL`, with zero triggered bear-warning signals.
- This is still review-only: `market_timing_claim_allowed=false`,
  `public_display_allowed=false`, `policy_hook_allowed=false`, and
  `live_trading_allowed=false`.
- Missing earnings/guidance coverage should be disclosed. The `BULL` label must
  not be promoted to public/production use without governance review.

## Internal R1 Run

The same input in `coverage_mode=internal` now computes:

| field | value |
|---|---:|
| status | `completed` |
| current_state | `BULL` |
| covered_signal_count | `9 / 12` |
| critical_group_coverage | `5 / 6` |
| public_display_allowed | `false` |
| policy_hook_allowed | `false` |

The internal and service computations now agree. Both remain review-only and
non-trading.

## Real-Data R1b Run

Command:

```powershell
C:\codex-shadow\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -B tools\run_chameleon_policy_audit.py `
  --regime-summary outputs\regime_nowcast_dial_realdata_service\summary.json `
  --output-dir outputs\chameleon_policy_audit_realdata_service
```

Output paths:

- `outputs/chameleon_policy_audit_realdata_service/summary.json`
- `outputs/chameleon_policy_audit_realdata_service/recommended_actions.csv`
- `outputs/chameleon_policy_audit_realdata_service/report.md`

Result:

| field | value |
|---|---:|
| status | `completed` |
| current_state | `BULL` |
| recommended_action_count | `3` |
| all_actions_review_only | `true` |
| executable_order_allowed | `false` |
| production_policy_mutation_allowed | `false` |
| live_trading_allowed | `false` |
| public_display_allowed | `false` |
| data_insufficient_no_allocation_guidance | `false` |

Recommended action labels:

- `normal_monthly_alphaops_target_process`
- `passed_replacement_quality_candidates`
- `cash_carry_accounting`

Interpretation:

- R1b behaved correctly.
- It did not produce executable orders.
- It did not mutate production policy.
- It stayed review-only despite the `BULL` state.

## What This Means

The M/R framework is wired safely enough for review-only diagnostics, and local
price plus macro caches now supply enough coverage for a computed service-mode
state. The remaining open question is governance: whether a review-only `BULL`
label may be shown internally or service-side while earnings/guidance coverage is
still missing.

The W4 connector path is now implemented and smoke-tested. What is missing is
the actual PIT earnings/guidance input file, not code plumbing.

The next engineering task is not a trading rule:

1. Provide or materialize `data_raw/events/earnings_revisions.csv` with
   `available_from` for every row, then run `build_earnings_revision_signals.py`.
2. Optionally replace SPY realized-volatility proxy with an explicit VIX/VIX3M
   feed when available.
3. Keep breadth and AI bucket RS sourced from price cache unless a broader
   universe breadth feed is added. The current breadth source is a cached-file
   breadth proxy, not an official R1000 membership breadth series.
4. Decide service/public wording for a computed-but-review-only market regime.

## Questions for GPT Pro

Use GPT Pro for governance and service-facing wording.

1. Given service mode now computes `BULL` with 9/12 signal coverage and W4
   plumbing is ready but the actual earnings/guidance feed is missing, should
   the public layer still hide regime completely?
2. If shown internally, should the label be `BULL`, `risk-on review`, or
   `market risk normal - review only`?
3. Should service mode require earnings/guidance coverage specifically, or is
   9/12 plus credit/liquidity coverage sufficient for a review-only regime
   label?
4. Is the wording "cash/T-bill-equivalent reserve label" safe enough, or should
   all T-bill references be removed until production accounting is decided?
5. Should the first public dashboard show only:
   - data freshness
   - forward ledger
   - review-only status
   and hide M/R until coverage is sufficient?

## Questions for Claude

Use Claude for code/path red-team.

1. Does the R1 macro-cache as-of handling correctly map slower Sahm/UNRATE
   observations to the nowcast date while preserving `source_observation_date`?
2. Should `state_override` remain as a research-only CLI option, or be removed
   entirely?
3. Does R1b fully prevent allocation guidance when R1 is `DATA_INSUFFICIENT`?
4. Are the new smokes sufficient:
   - critical group data insufficiency
   - price-cache-derived volatility/breadth/AI coverage
   - macro-cache-derived credit/liquidity coverage
   - earnings/guidance PIT `available_from` filter
   - no executable orders
   - data insufficient no allocation guidance
   - state override ignored by default
   - R2 era gate
5. Are the HY OAS, 10Y-3M, and Sahm thresholds reasonable as review-only
   nowcast inputs, or should they be calibration-only until a longer validation?

## Recommended Next Step

Do not build a regime overlay hook.
Do not run fullrun.
Do not send M/R to production or public display.

Next Codex task should be:

1. Send this packet to GPT Pro for service-facing wording/governance.
2. Send this packet to Claude for code/path red-team of macro as-of handling.
3. Provide or materialize the W4 PIT earnings/guidance feed before treating
   earnings/guidance as covered.
4. Do not connect R1/R1b to production hooks or fullrun.
