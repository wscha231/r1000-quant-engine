# CODEX Earnings / Guidance Feed Contract - 2026-07-04

## Purpose

This contract defines the raw PIT earnings revision and guidance feed required
by W4. It is a data contract, not a trading rule, production activation, or
fullrun trigger.

The feed is consumed by:

- `tools/validate_earnings_revision_feed.py`
- `tools/build_earnings_revision_signals.py`
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

Do not use fallback `actual_results_score` as a substitute for this feed in R1.
Fallbacks can remain diagnostic in other screens, but not in the service-facing
market-state nowcast.

