# Data Freshness Contract

- status: `pass`
- selection_allowed: `true`
- promotion_allowed: `false`
- latest_observable_close_date: `2026-06-26`
- effective_latest_target_date: `2026-06-26`
- production_mutation_allowed: `false`

## Blockers

- none

## Warnings

- dated target snapshot archive is missing for this run
- etf coverage 0.0 < floor 0.3
- free_data_manifest is missing (latest_asof=)
- latest target date 2026-06-29 is after latest observable close 2026-06-26; freshness gate uses observable close
- macro freshness uses directory_mtime_proxy; add a macro latest_manifest.json/asof watermark
- sec_v1_evidence coverage 0.1201359787907295 < floor 0.2

## Watermarks

| source | status | latest_asof | age_days | cadence_days | owner |
| --- | --- | --- | ---: | ---: | --- |
| prices | ok | 2026-06-26 | 3.0 | 3 | free_data_daily_update.yml |
| daily_market_snapshot | ok | 2026-06-29T12:35:19.789294+00:00 | 0.0 | 3 | daily_operating_selection_refresh.yml |
| macro | ok | 2026-06-29T12:35:21.046646+00:00 | 0.0 | 3 | daily_crisis_monitor.yml/free_data_daily_update.yml |
| sec_companyfacts | ok | 2026-06-29T09:11:18.411408+00:00 | 0.0 | 7 | data_readiness_preflight.yml/free_data_daily_update.yml |
| form4_transactions | ok | 2026-06-27T01:37:09.706000+00:00 | 2.0 | 5 | sec_form4_daily_refresh.yml |
| institutional_13f_holdings | ok | 2026-05-25T07:27:21.847000+00:00 | 35.0 | 100 | sec_13f_quarterly_refresh.yml |
| etf_holdings | ok | 2026-06-09T16:59:50.667000+00:00 | 20.0 | 40 | etf_holdings_monthly_refresh.yml |
| free_data_manifest | missing |  |  | 3 | free_data_daily_update.yml |

## Evidence Coverage

- `etf`: status `WARN`, coverage `0.0`, floor `0.3`
- `sec_v1_evidence`: status `WARN`, coverage `0.1201359787907295`, floor `0.2`
- `13f`: status `ok`, coverage `0.7782647737962883`, floor `0.5`
- `smart_money`: status `ok`, coverage `0.7324467630206106`, floor `0.5`
- `top_manager`: status `ok`, coverage `0.6861370050457539`, floor `0.05`
