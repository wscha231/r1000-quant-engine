# Data Freshness Contract

- status: `pass`
- selection_allowed: `true`
- promotion_allowed: `false`
- latest_observable_close_date: `2026-06-17`
- effective_latest_target_date: `2026-04-30`
- production_mutation_allowed: `false`

## Blockers

- none

## Warnings

- daily_market_snapshot is missing (latest_asof=)
- dated target snapshot archive is missing for this run
- etf coverage 0.0 < floor 0.3
- free_data_manifest is missing (latest_asof=)
- macro freshness uses directory_mtime_proxy; add a macro latest_manifest.json/asof watermark
- sec_v1_evidence coverage 0.13433270266336778 < floor 0.2

## Watermarks

| source | status | latest_asof | age_days | cadence_days | owner |
| --- | --- | --- | ---: | ---: | --- |
| prices | ok | 2026-06-18 | 1.0 | 3 | free_data_daily_update.yml |
| daily_market_snapshot | missing |  |  | 3 | daily_operating_selection_refresh.yml |
| macro | ok | 2026-06-19T12:09:28.018649+00:00 | 0.0 | 3 | daily_crisis_monitor.yml/free_data_daily_update.yml |
| sec_companyfacts | ok | 2026-06-19T08:38:42.169828+00:00 | 0.0 | 7 | data_readiness_preflight.yml/free_data_daily_update.yml |
| form4_transactions | ok | 2026-06-19T02:20:10.970000+00:00 | 0.0 | 5 | sec_form4_daily_refresh.yml |
| institutional_13f_holdings | ok | 2026-05-25T07:27:21.847000+00:00 | 25.0 | 100 | sec_13f_quarterly_refresh.yml |
| etf_holdings | ok | 2026-06-09T16:59:50.667000+00:00 | 10.0 | 40 | etf_holdings_monthly_refresh.yml |
| free_data_manifest | missing |  |  | 3 | free_data_daily_update.yml |

## Evidence Coverage

- `etf`: status `WARN`, coverage `0.0`, floor `0.3`
- `sec_v1_evidence`: status `WARN`, coverage `0.13433270266336778`, floor `0.2`
- `13f`: status `ok`, coverage `0.7830252753116965`, floor `0.5`
- `smart_money`: status `ok`, coverage `0.7330325522728375`, floor `0.5`
- `top_manager`: status `ok`, coverage `0.6849560956677825`, floor `0.05`
