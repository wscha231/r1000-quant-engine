# Data Freshness Contract

- status: `blocked`
- selection_allowed: `false`
- promotion_allowed: `false`
- latest_observable_close_date: `2026-06-18`
- effective_latest_target_date: `2026-06-18`
- production_mutation_allowed: `false`

## Blockers

- prices is stale (latest_asof=2026-06-18)

## Warnings

- dated target snapshot archive is missing for this run
- etf coverage 0.0 < floor 0.3
- free_data_manifest is missing (latest_asof=)
- latest target date 2026-06-22 is after latest observable close 2026-06-18; freshness gate uses observable close
- macro freshness uses directory_mtime_proxy; add a macro latest_manifest.json/asof watermark
- price cache manifest is stale by 4 calendar days
- sec_v1_evidence coverage 0.12130509939498703 < floor 0.2

## Watermarks

| source | status | latest_asof | age_days | cadence_days | owner |
| --- | --- | --- | ---: | ---: | --- |
| prices | stale | 2026-06-18 | 4.0 | 3 | free_data_daily_update.yml |
| daily_market_snapshot | ok | 2026-06-22T05:23:55.035625+00:00 | 0.0 | 3 | daily_operating_selection_refresh.yml |
| macro | ok | 2026-06-22T05:23:56.282869+00:00 | 0.0 | 3 | daily_crisis_monitor.yml/free_data_daily_update.yml |
| sec_companyfacts | ok | 2026-06-22T01:48:17.782903+00:00 | 0.0 | 7 | data_readiness_preflight.yml/free_data_daily_update.yml |
| form4_transactions | ok | 2026-06-20T01:49:30.395000+00:00 | 2.0 | 5 | sec_form4_daily_refresh.yml |
| institutional_13f_holdings | ok | 2026-05-25T07:27:21.847000+00:00 | 28.0 | 100 | sec_13f_quarterly_refresh.yml |
| etf_holdings | ok | 2026-06-09T16:59:50.667000+00:00 | 13.0 | 40 | etf_holdings_monthly_refresh.yml |
| free_data_manifest | missing |  |  | 3 | free_data_daily_update.yml |

## Evidence Coverage

- `etf`: status `WARN`, coverage `0.0`, floor `0.3`
- `sec_v1_evidence`: status `WARN`, coverage `0.12130509939498703`, floor `0.2`
- `13f`: status `ok`, coverage `0.7787381158167676`, floor `0.5`
- `smart_money`: status `ok`, coverage `0.7325842696629213`, floor `0.5`
- `top_manager`: status `ok`, coverage `0.6862143474503025`, floor `0.05`
