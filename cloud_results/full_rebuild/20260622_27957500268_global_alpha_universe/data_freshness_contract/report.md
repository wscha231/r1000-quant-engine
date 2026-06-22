# Data Freshness Contract

- status: `pass`
- selection_allowed: `true`
- promotion_allowed: `false`
- latest_observable_close_date: `2026-06-22`
- effective_latest_target_date: `2026-06-22`
- production_mutation_allowed: `false`

## Blockers

- none

## Warnings

- dated target snapshot archive is missing for this run
- etf coverage 0.0 < floor 0.3
- free_data_manifest is missing (latest_asof=)
- macro freshness uses directory_mtime_proxy; add a macro latest_manifest.json/asof watermark
- sec_v1_evidence coverage 0.12122200478364861 < floor 0.2

## Watermarks

| source | status | latest_asof | age_days | cadence_days | owner |
| --- | --- | --- | ---: | ---: | --- |
| prices | ok | 2026-06-22 | 0.0 | 3 | free_data_daily_update.yml |
| daily_market_snapshot | ok | 2026-06-22T16:17:25.400314+00:00 | 0.0 | 3 | daily_operating_selection_refresh.yml |
| macro | ok | 2026-06-22T16:17:26.414777+00:00 | 0.0 | 3 | daily_crisis_monitor.yml/free_data_daily_update.yml |
| sec_companyfacts | ok | 2026-06-22T14:00:07.808725+00:00 | 0.0 | 7 | data_readiness_preflight.yml/free_data_daily_update.yml |
| form4_transactions | ok | 2026-06-20T01:49:30.395000+00:00 | 2.0 | 5 | sec_form4_daily_refresh.yml |
| institutional_13f_holdings | ok | 2026-05-25T07:27:21.847000+00:00 | 28.0 | 100 | sec_13f_quarterly_refresh.yml |
| etf_holdings | ok | 2026-06-09T16:59:50.667000+00:00 | 13.0 | 40 | etf_holdings_monthly_refresh.yml |
| free_data_manifest | missing |  |  | 3 | free_data_daily_update.yml |

## Evidence Coverage

- `etf`: status `WARN`, coverage `0.0`, floor `0.3`
- `sec_v1_evidence`: status `WARN`, coverage `0.12122200478364861`, floor `0.2`
- `13f`: status `ok`, coverage `0.7786910197869102`, floor `0.5`
- `smart_money`: status `ok`, coverage `0.732572298325723`, floor `0.5`
- `top_manager`: status `ok`, coverage `0.686105675146771`, floor `0.05`
