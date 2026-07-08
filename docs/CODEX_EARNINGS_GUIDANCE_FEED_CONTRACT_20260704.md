# CODEX Earnings / Guidance Feed Contract - 2026-07-04

## Purpose

This contract defines the raw PIT earnings revision and guidance feed required
by W4. It is a data contract, not a trading rule, production activation, or
fullrun trigger.

The feed is consumed by:

- `tools/validate_earnings_revision_feed.py`
- `tools/build_earnings_revision_signals.py`
- `tools/check_earnings_guidance_coverage.py`
- `tools/run_regime_nowcast_dial.py --earnings-signals`

## Required Raw File

Path:

`data_raw/events/earnings_revisions.csv`

Required columns:

- `ticker`
- `available_from`

Recommended columns:

- `fiscal_period`
- `estimate_date`
- `eps_estimate`
- `revenue_estimate`
- `margin_estimate`
- `guidance_direction`
- `source`
- `source_type`

Optional actual-comparison columns:

- `actual_eps_ttm`
- `actual_revenue_ttm`
- `actual_margin_ttm`

Optional valuation columns:

- `forward_pe`
- `forward_pe_5y_avg`
- `forward_pe_10y_avg`

## PIT Rules

- Every row must have `available_from`.
- `available_from` must be the first date the system could have known the
  estimate/guidance value.
- `estimate_date` can be earlier than `available_from`, but never substitutes
  for it.
- Rows with `available_from > as_of_date` are filtered by the builder and must
  not influence any signal.
- No forward returns, future labels, realized alpha, or post-window outcome
  fields may be used.
- Actual-comparison columns must also be point-in-time. They should represent
  the latest reported actuals the system could know by `available_from`, not a
  restated or future fiscal value.

## Signal Fields Built

When enough dated observations are present, the builder emits:

- short-horizon estimate revisions: `eps_revision_1d`, `eps_revision_5d`,
  `eps_revision_20d`, `eps_revision_63d`, and matching revenue fields
- legacy revision windows: `eps_revision_4w`, `eps_revision_13w`,
  `eps_revision_26w`, `revenue_revision_13w`
- revision acceleration / deceleration: `eps_revision_accel_5d_vs_20d`,
  `eps_revision_accel_20d_vs_63d`,
  `revenue_revision_accel_5d_vs_20d`,
  `revenue_revision_accel_20d_vs_63d`,
  `eps_down_revision_deceleration_score`,
  `revenue_down_revision_deceleration_score`
- current-actual comparison gaps: `eps_estimate_vs_actual_ttm`,
  `revenue_estimate_vs_actual_ttm`, `margin_estimate_vs_actual_ttm`

## Guidance Values

Accepted positive values:

- `positive`
- `raise`
- `raised`
- `up`
- `beat`
- `above`

Accepted negative values:

- `negative`
- `cut`
- `lower`
- `lowered`
- `down`
- `miss`
- `below`

Other values are neutral.

## Source Types

Allowed `source_type` values:

- `historical_revision`
- `vendor_estimate_revision`
- `company_guidance`
- `sec_actual_snapshot`
- `current_snapshot`
- `manual_research_import`

`current_snapshot` data can be used only as current research context. It is not
enough for 7Y policy acceptance, control reproduction, or production evidence.
For R1 service coverage, the feed must contain enough revision/guidance
evidence to avoid turning a placeholder CSV into a false `covered` signal.

Only these `source_type` values count toward R1 earnings/guidance coverage:

- `historical_revision`
- `vendor_estimate_revision`
- `company_guidance`
- `manual_research_import`

`sec_actual_snapshot` and `current_snapshot` rows are allowed for inventory and
diagnostics, but they are actual/current context, not true analyst revision or
guidance history. They must not make `regime_nowcast_coverage_ready=true`.

## Regime Coverage Guard

The old smoke-level threshold of 5 rows/tickers is only `plumbing_ready`.
The feed is considered usable for the R1 earnings/guidance critical group only
when `research_ready=true` from `tools/check_earnings_guidance_coverage.py`.

Plumbing is ready when at least one of these is true:

- at least 5 coverage-eligible rows exist, or
- at least 5 coverage-eligible tickers exist.

These only prove wiring. They are not service or research coverage.

Research is ready only when at least one of these stronger conditions is true:

- at least 10 coverage-eligible tickers have 2 or more dated estimate
  observations, observation span is at least 14 days, and data recency is at
  most 30 days; or
- at least 10 directional guidance rows cover at least 5 tickers, with data
  recency at most 30 days.

Neutral-only, zero-only, header-only, or valuation-only files remain valid
inputs for diagnostics but must not count as R1 earnings/guidance coverage.

## Validation Commands

Validate raw feed:

```powershell
C:\codex-shadow\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -B tools\validate_earnings_revision_feed.py `
  --input data_raw\events\earnings_revisions.csv `
  --summary outputs\earnings_revision_feed_contract\summary.json `
  --as-of 2026-07-01
```

Build PIT signals:

```powershell
C:\codex-shadow\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -B tools\build_earnings_revision_signals.py `
  --input data_raw\events\earnings_revisions.csv `
  --output data_pit\events\earnings_revision_signals.parquet `
  --summary outputs\earnings_revision_signals\summary.json `
  --as-of 2026-07-01
```

Re-run R1 with the built feed:

```powershell
C:\codex-shadow\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -B tools\run_regime_nowcast_dial.py `
  --price-cache outputs\p4_cap_replacement_broker_counterfactual_28616190134\cache_prices `
  --macro-cache cache_macro `
  --earnings-signals data_pit\events\earnings_revision_signals.parquet `
  --as-of-date 2026-07-01 `
  --coverage-mode service `
  --output-dir outputs\regime_nowcast_dial_realdata_service
```

## Current Status

As of this commit, the code path is ready and smoke-tested, but the actual raw
feed is missing:

- Missing input: `data_raw/events/earnings_revisions.csv`
- R1 therefore still reports missing `earnings_guidance` coverage on real data.
- Header-only, neutral-only, actual-only, or current-snapshot-only CSV files are
  intentionally blocked/ignored for R1 coverage.

Do not use fallback `actual_results_score` as a substitute for this feed in R1.
Fallbacks can remain diagnostic in other screens, but not in the service-facing
market-state nowcast.
