# Data Freshness Contract

- status: `pass`
- selection_allowed: `true`
- promotion_allowed: `false`
- latest_observable_close_date: `2026-07-02`
- effective_latest_target_date: `2026-07-02`
- production_mutation_allowed: `false`

## Blockers

- none

## Warnings

- dated target snapshot archive is missing for this run
- etf coverage 0.0 < floor 0.3
- free_data_manifest is missing (latest_asof=)
- macro freshness uses directory_mtime_proxy; add a macro latest_manifest.json/asof watermark
- sec_v1_evidence coverage 0.12185095393696638 < floor 0.2

## Watermarks

| source | status | latest_asof | age_days | cadence_days | owner |
| --- | --- | --- | ---: | ---: | --- |
| prices | ok | 2026-07-02 | 3.0 | 3 | free_data_daily_update.yml |
| daily_market_snapshot | ok | 2026-07-05T04:11:21.539667+00:00 | 0.0 | 3 | daily_operating_selection_refresh.yml |
| macro | ok | 2026-07-05T04:11:22.591939+00:00 | 0.0 | 3 | daily_crisis_monitor.yml/free_data_daily_update.yml |
| sec_companyfacts | ok | 2026-07-05T01:23:01.909439+00:00 | 0.0 | 7 | data_readiness_preflight.yml/free_data_daily_update.yml |
| form4_transactions | ok | 2026-07-04T01:09:10.423000+00:00 | 1.0 | 5 | sec_form4_daily_refresh.yml |
| institutional_13f_holdings | ok | 2026-05-25T07:27:21.847000+00:00 | 41.0 | 100 | sec_13f_quarterly_refresh.yml |
| etf_holdings | ok | 2026-07-02T01:58:43.753000+00:00 | 3.0 | 40 | etf_holdings_monthly_refresh.yml |
| free_data_manifest | missing |  |  | 3 | free_data_daily_update.yml |

## Evidence Coverage

- `etf`: status `WARN`, coverage `0.0`, floor `0.3`
- `sec_v1_evidence`: status `WARN`, coverage `0.12185095393696638`, floor `0.2`
- `13f`: status `ok`, coverage `0.7783282386423527`, floor `0.5`
- `smart_money`: status `ok`, coverage `0.7322019605776325`, floor `0.5`
- `top_manager`: status `ok`, coverage `0.6852745862759566`, floor `0.05`
