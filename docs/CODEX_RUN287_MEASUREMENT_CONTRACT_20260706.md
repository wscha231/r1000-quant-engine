# Run 287 Measurement Contract

Status: research-only, production-blocked.

This contract applies to GitHub Actions run `28725350727` and any local
forensic package built from its artifacts.

## Non-Negotiables

- Do not dispatch another fullrun for this attribution pass.
- Do not add a new alpha hook.
- Do not tune thresholds from the losing July dates, months, or tickers.
- Do not label any result `production_ready`, `live_trading_ready`, or public
  service performance while `pit_universe_label_clean=false`.
- Do not use the `2026-06-29` clamp as a current pass label. It is an
  attribution cell only.
- Do not treat frozen-book replay metrics as regenerated fullrun acceptance.

## Required Performance Fields

Every performance table must declare:

- `metric_mode`
- `target_book_source`
- `replay_start_date`
- `replay_end_date`
- `actual_equity_curve_end_date`
- `price_cache_hash` or `price_cache_status`
- `cash_rate_source` and hash when cash-carry is used
- hook flags and hook telemetry source
- `pit_universe_label_clean`
- `production_promotion_allowed`
- `public_display_allowed`
- `live_trading_enabled`

## Metric Contract

`broker_ledger_next_close` remains the zero-yield side-by-side reference.

`broker_ledger_next_close_cash_carry` is an official research accounting mode
only when replayed from the same generated target book, same price cache, same
fill policy, and same replay window. It requires:

- DGS3MO
- 1 business-day lag
- ACT/365 day count
- 50 bps haircut
- explicit cash-rate cache hash

If `cache_prices` is absent, or if it contains only
`replay_price_cache_manifest.json` without ticker price files, exact
generated-book cash-carry replay is blocked. Do not estimate it from the equity
curve and report it as official.

## Comparison Rules

Valid decision-relevant comparisons require the same:

- target-book source
- metric mode
- replay end date
- price cache
- accounting contract

Frozen-book results may be used as fixed-book research evidence. Regenerated
book results may be used as fullrun evidence. They are not interchangeable.

The first local forensic matrix must decompose:

- zero-yield official reproduction
- 2026-06-29 vs 2026-07-02 window effect
- frozen-book vs regenerated-book drift
- hook telemetry presence
- exact cash-carry replay readiness

Hook contribution needs a hook-off counterfactual on the same generated book.
Hook applied counts alone are telemetry, not proof of positive contribution.

## Anti-Leakage Gates

Attribution is diagnostic. It must not become hand-edited hindsight fitting.

Forbidden:

- preserving a ticker because it later won
- dropping a ticker because it later lost
- choosing `2026-06-29` because it avoids the July shock
- replacing rank or revenue thresholds after observing run287 losses
- quoting cash-yield uplift as selection alpha

Allowed:

- writing negative evidence
- restoring the price cache for exact replay
- forcing deterministic target generation before future regenerated-book drift
  analysis
- proposing a single ex-ante rule only after the attribution report identifies
  a general, decision-time observable failure mode

## Decision Labels

Allowed labels:

- `measurement_mismatch_only`
- `window_shock_explains_drop`
- `regenerated_book_drift_explains_drop`
- `hook_event_mismatch_explains_drop`
- `alpha_candidate_rejected_on_generated_book`
- `blocked_unreproducible`
- `production_blocked_research_pass`
- `ready_for_human_review`

Forbidden labels:

- `production_ready`
- `live_candidate`
- `public_return_claim`
- `official_service_performance`

## Current Local Status

The first local package is `outputs/run287_forensics`.

The latest-basis replay price cache has been rebuilt under
`outputs/run287_price_cache_latest/cache_prices`. Its manifest reports:

- `actual_cached_ticker_count=498`
- `failed_count=0`
- `start=2019-05-09`
- `end=2026-07-02`
- `manifest_end_source=actual_cached_bars`

Exact generated-book cash-carry replay has been run locally under
`outputs/run287_metric_sidecar/generated_book_cash_carry`.

Current official research baseline for run287 latest-basis generated-book
measurement:

| Portfolio | Metric mode | CAGR | MaxDD | Sharpe | Target pass |
| --- | --- | ---: | ---: | ---: | --- |
| Main | `broker_ledger_next_close` | 32.94% | -25.65% | 1.237 | false |
| Main | `broker_ledger_next_close_cash_carry` | 33.81% | -25.36% | 1.262 | false |
| Concentrated | `broker_ledger_next_close` | 47.00% | -23.22% | 1.455 | false |
| Concentrated | `broker_ledger_next_close_cash_carry` | 48.41% | -22.96% | 1.488 | false |

Decision label: `alpha_candidate_rejected_on_generated_book`.

This means the latest generated-book drop is not a cash-carry-only measurement
mismatch. Do not tune thresholds from this run. Write negative evidence and
prioritize W1 determinism, window attribution, and target-book drift before any
new alpha work.

Interpretation correction:

- The main drop versus the frozen `2026-06-29` cash-carry candidate is mostly
  the honest `2026-07-02` window containing the late-June/early-July shock, not
  a proven hook failure.
- The frozen `36.33% / 52.14%` values stopped at `2026-06-29`; the run287
  latest-basis baseline includes the `2026-06-30` through `2026-07-02` move.
- Hook applied counts remain telemetry only until a same-book hook-off
  counterfactual exists.

## W1 Determinism Status

Current-code same-machine target generation was rerun twice under
`outputs/run287_w1_determinism_exact` with:

- frozen policy payload env
- `R1000_CATBOOST_TASK_TYPE=CPU`
- latest local price cache ending `2026-07-02`
- run287 artifact crisis features and thresholds
- `shadow_only` output mode
- no broker replay, no fullrun, no production mutation

Double-run audit result:

| Portfolio | official_only_date_count | generated_only_date_count | ticker_mismatch_date_count | max_weight_delta_abs | Exact pass |
| --- | ---: | ---: | ---: | ---: | --- |
| Main | 0 | 0 | 0 | 0.0 | true |
| Concentrated | 0 | 0 | 0 | 0.0 | true |

Boundary: this proves same-input local determinism on the restored run287
substrate. It does not prove official artifact parity because the local
candidate-generation price cache is still smaller than the original run287
runner cache.

## Rolling Deficit Status

`outputs/run287_rolling_window_deficit` measures generated-book cash-carry
end-date sensitivity from existing equity curves only. It does not replay,
dispatch, mutate target books, or tune thresholds.

Key results:

| Portfolio | 2026-06-29 CAGR / MaxDD | 2026-07-02 CAGR / MaxDD | Delta CAGR | Last 20 CAGR percentile | Last 20 pass rate | Last 252 pass rate |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Main | 35.57% / -25.36% | 33.81% / -25.36% | -1.77pp | 10.0% | 0.0% | 0.0% |
| Concentrated | 50.67% / -22.96% | 48.41% / -22.96% | -2.27pp | 25.0% | 35.0% | 2.8% |

Interpretation:

- Main is not only a two-day shock issue. Its 2026-06-29 CAGR clears 35%, but
  the -25.36% MDD already fails. Main needs exit-latency or structural MDD
  evidence, not a shock predictor fitted to July.
- Concentrated is more end-date sensitive: 2026-06-29 passes and 2026-07-02
  fails. Still, the last-252 endpoint pass rate is only 2.8%, so chasing exactly
  50% on one endpoint is not robust alpha evidence.

## Main Exit-Latency Status

`outputs/run287_exit_latency` audits the generated-book cash-carry Main
max-drawdown window from existing artifacts only. It does not replay trades,
dispatch a fullrun, mutate target books, tune thresholds, or create a crash
predictor.

Key results:

| Field | Value |
| --- | ---: |
| MaxDD window | `2021-11-19` to `2022-09-26` |
| MaxDD | -25.36% |
| hard_signal_count | 12 |
| material_latency_count | 0 |
| latency_candidate_present | false |

Diagnosis:
`hard_signals_found_but_latency_or_post_signal_loss_not_material`.

Interpretation:

- Top drawdown contributors had hard exit/reduction signals, but the actual
  book generally aligned within 1 to 3 calendar days.
- Main exit-latency is not an identified material MDD lever on this evidence.
- Do not build a July/2022 shock guard, and do not directly edit losing
  drawdown tickers.
