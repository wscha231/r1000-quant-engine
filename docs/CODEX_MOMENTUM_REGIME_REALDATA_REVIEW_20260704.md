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
  --only chameleon_policy_audit_smoke `
  --only chameleon_policy_no_orders_smoke `
  --only chameleon_policy_data_insufficient_no_allocation_smoke `
  --only state_override_service_forbidden_smoke `
  --only state_conditional_ic_audit_smoke `
  --only state_conditional_ic_era_gate_smoke
```

Result:

- 11/11 PASS.

## Real-Data R1 Run

Command:

```powershell
C:\codex-shadow\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -B tools\run_regime_nowcast_dial.py `
  --price-cache outputs\p4_cap_replacement_broker_counterfactual_28616190134\cache_prices `
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

Output paths:

- `outputs/regime_nowcast_dial_realdata_service/summary.json`
- `outputs/regime_nowcast_dial_realdata_service/signal_panel.csv`
- `outputs/regime_nowcast_dial_realdata_service/indicator_rows.csv`
- `outputs/regime_nowcast_dial_realdata_service/state_history.csv`
- `outputs/regime_nowcast_dial_realdata_service/report.md`

Result:

| field | value |
|---|---:|
| status | `data_insufficient` |
| current_state | `DATA_INSUFFICIENT` |
| bear_warning_score | `0` |
| bear_warning_label | `risk_on` |
| covered_signal_count | `6 / 12` |
| signal_coverage | `0.50` |
| critical_group_coverage | `4 / 6` |
| data_insufficient_reason | `covered_signals_lt_8_for_service` |
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

Missing critical groups:

- `credit_liquidity`
- `earnings_guidance`

Missing warning signals:

- `eps_revision_breadth_negative`
- `hy_oas_widening_threshold`
- `positive_guidance_ratio_deteriorating`
- `sahm_unemployment_momentum_warning`
- `soxx_smh_rs_negative_vs_qqq`
- `yield_curve_inversion_or_steepening_warning`

Interpretation:

- The local price cache now covers enough for a research/internal state
  calculation, but service mode still correctly blocks any market-state claim.
- The service-mode block is now narrower and more informative: the missing
  pieces are credit/liquidity and earnings/guidance, not price-cache plumbing.
- `bear_warning_score=0` should not be displayed as a market call while
  `current_state=DATA_INSUFFICIENT`.
- No current-regime claim should be made from this run.

## Internal R1 Run

The same input in `coverage_mode=internal` now computes:

| field | value |
|---|---:|
| status | `completed` |
| current_state | `BULL` |
| covered_signal_count | `6 / 12` |
| critical_group_coverage | `4 / 6` |
| public_display_allowed | `false` |
| policy_hook_allowed | `false` |

This internal state is useful for diagnostics only. It is not sufficient for a
service-facing regime label because service mode requires at least 8 warning
signals and still lacks credit/liquidity plus earnings/guidance coverage.

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
| current_state | `DATA_INSUFFICIENT` |
| recommended_action_count | `3` |
| all_actions_review_only | `true` |
| executable_order_allowed | `false` |
| production_policy_mutation_allowed | `false` |
| live_trading_allowed | `false` |
| public_display_allowed | `false` |
| data_insufficient_no_allocation_guidance | `true` |

Recommended action labels:

- `data_review_required`
- `no_current_regime_claim`
- `expand_r1_coverage`

Interpretation:

- R1b behaved correctly.
- It did not produce allocation guidance.
- It did not say to buy T-bills, sell stocks, or time the market.
- It only asks for data coverage review.

## What This Means

The M/R framework is wired safely enough for review-only diagnostics, and the
local price cache now supplies the price-derived critical groups. The current
local data is still not sufficient to make a service-facing regime claim.

The next engineering task remains data coverage, not a trading rule:

1. Add credit/liquidity coverage (HY OAS and yield-curve local macro cache).
2. Add earnings/guidance coverage only after W4 PIT feed exists.
3. Optionally replace SPY realized-volatility proxy with an explicit VIX/VIX3M
   feed when available.
4. Keep breadth and AI bucket RS sourced from price cache unless a broader
   universe breadth feed is added. The current breadth source is a cached-file
   breadth proxy, not an official R1000 membership breadth series.

## Questions for GPT Pro

Use GPT Pro for governance and service-facing wording.

1. Given this first real-data run produced `DATA_INSUFFICIENT`, should the public
   layer hide regime completely, or show a neutral "market risk review pending"
   label?
2. Is `bear_warning_score=0` too dangerous to store/display when coverage is
   6/12 and state is still `DATA_INSUFFICIENT`?
3. Should service mode require credit/liquidity coverage specifically, beyond
   the current 8-of-12 signal count plus 4-of-6 critical-group rule?
4. Is the wording "cash/T-bill-equivalent reserve label" safe enough, or should
   all T-bill references be removed until production accounting is decided?
5. Should the first public dashboard show only:
   - data freshness
   - forward ledger
   - review-only status
   and hide M/R until coverage is sufficient?

## Questions for Claude

Use Claude for code/path red-team.

1. Does the R1 service-mode `DATA_INSUFFICIENT` logic correctly prevent false
   market-state claims?
2. Should `state_override` remain as a research-only CLI option, or be removed
   entirely?
3. Does R1b fully prevent allocation guidance when R1 is `DATA_INSUFFICIENT`?
4. Are the new smokes sufficient:
   - critical group data insufficiency
   - price-cache-derived volatility/breadth/AI coverage
   - no executable orders
   - data insufficient no allocation guidance
   - state override ignored by default
   - R2 era gate
5. Which remaining coverage source should be added first:
   - credit/liquidity
   - earnings/guidance
   - explicit VIX/VIX3M, replacing the current SPY realized-volatility proxy

## Recommended Next Step

Do not build a regime overlay hook.
Do not run fullrun.
Do not send M/R to production or public display.

Next Codex task should be:

1. Materialize credit/liquidity signals from existing macro sources if available
   (`HY OAS`, `10Y-3M`, Sahm/unemployment momentum).
2. Keep earnings/guidance missing until a PIT W4 feed exists.
3. Re-run R1 service mode.
4. Only if R1 leaves `DATA_INSUFFICIENT`, send the actual computed state and
   R1b actions for external review.
