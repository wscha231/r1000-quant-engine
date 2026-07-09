# Codex Forward Earnings Estimate Feed - 2026-07-09

## Verdict

Adopt the Claude directive with one safety adjustment: the daily estimate
archive is persisted through GitHub artifacts/cache and optional Google Drive
sync, not committed into the repository. This keeps the repository from turning
into a growing data lake while still starting a forward-only PIT archive.

This is a backend-only, default-OFF feed. It does not dispatch a fullrun, does
not alter historical backtests, does not add an alpha hook, and does not enable
production or live trading.

## Scope

Implemented:

- `tools/collect_earnings_estimates_finnhub.py`
- `.github/workflows/earnings_estimates_daily.yml`
- `PHASE18_ESTIMATE_REVISION_COLUMNS`
- `PHASE_ESTIMATE_REVISION_CONFIRM_ENABLED=false` by default
- fixture-based collector and feature smokes
- backtest-neutrality static smoke
- latest-confirmation default-OFF smoke

Not implemented:

- no fullrun
- no feature-store or walk-forward integration
- no historical backtest acceptance claim
- no stock-selection mutation while the flag is off
- no retroactive estimate backfill

## Measurement And Leakage Contract

The archive begins only when the daily job starts running. `available_from` is
the fetch date, not a fiscal-period date or report date. Current snapshots are
therefore valid for forward monitoring only. They cannot be pasted into the
2019-2026 replay window.

Historical acceptance still requires a paid PIT estimate-history source such as
I/B/E/S, FactSet, or Zacks historical. Without that source, this feed can build
future evidence but cannot explain or improve the run287 7Y CAGR/MDD result.

## Built Columns

The collector writes daily snapshots under:

- `data_pit/events/earnings_estimates/estimates_YYYYMMDD.parquet`

and rolling signals under:

- `data_pit/events/earnings_revision_signals.parquet`

The rolling signal columns include:

- `est_eps_fy1`
- `est_eps_fy2`
- `est_rev_fy1`
- `est_eps_revision_30d`
- `est_eps_revision_90d`
- `est_eps_revision_breadth`
- `est_rev_revision_30d`
- `est_dispersion`
- `est_dispersion_change_30d`
- `earnings_surprise_last`
- `surprise_streak`
- `estimate_revision_confirmed`
- `estimate_revision_replacement_gate_pass`
- `estimate_revision_future_winner_multiplier`

## Latest-Only Confirmation Helper

`apply_estimate_revision_confirmation()` is default-OFF and only consumes rows
with `available_from <= decision_date`. When enabled in a latest-scoring caller,
it can:

- mark Concentrated replacement candidates as confirmed only when revision
  breadth is positive and estimate dispersion is narrowing
- apply a bounded future-winner multiplier capped at +/-5%

It is intentionally not imported by `r1000_pipeline.py` in this patch. The smoke
test asserts the Phase 18 columns are not in `DEFAULT_FEATURES` and are not
referenced by the backtest pipeline.

## Daily Workflow

`.github/workflows/earnings_estimates_daily.yml` runs on schedule and manual
dispatch. It:

- restores prior archive from cache/GDrive when available
- calls Finnhub using `FINNHUB_API_KEY`
- writes the daily snapshot and rolling signals
- uploads artifacts
- syncs to Google Drive when configured

The scheduled default ticker set is bounded. A broader universe can be supplied
manually through `tickers`, `universe_file`, and `ticker_limit`.

## Vendor Entitlement Handling

The first manual run on `master` reached GitHub Actions and proved the workflow
registration path, but Finnhub returned HTTP 403 for `/stock/eps-estimate` on
the configured key. That means the current key is valid enough to call Finnhub
but is not entitled for the true forward-estimate endpoint.

The collector treats this as a data-entitlement block, not a strategy result:

- `status=blocked_vendor_entitlement`
- `reason=finnhub_estimate_endpoint_forbidden`
- `vendor_estimate_access=false`
- `backtest_acceptance_allowed=false`
- `production_activation_allowed=false`
- `live_trading_enabled=false`

API tokens are redacted before any error string is written to artifacts or
Google Drive. A blocked entitlement run exits successfully so scheduled jobs do
not repeatedly fail while still preserving a loud machine-readable summary.

## Validation

- `tests/collect_earnings_estimates_smoke.py`
- `tests/estimate_revision_features_smoke.py`
- `tests/estimate_feed_backtest_neutrality_smoke.py`
- `tests/estimate_confirm_selection_smoke.py`

These are registered in `tools/run_pr_validation.py`.

## Next Decision

Start the forward archive now. Use it for forward paper-ledger evidence only.
If Concentrated still needs historical proof, reopen D2 and decide whether to
buy paid PIT estimate history.
