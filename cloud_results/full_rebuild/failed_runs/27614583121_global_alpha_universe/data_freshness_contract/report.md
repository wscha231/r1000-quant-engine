# Data Freshness Contract

- status: `blocked`
- selection_allowed: `false`
- promotion_allowed: `false`
- latest_observable_close_date: `2026-06-12`
- effective_latest_target_date: `2026-06-12`
- production_mutation_allowed: `false`

## Blockers

- data_readiness.ready_for_policy_replay is false
- scored_latest.csv row count is below threshold: 259

## Warnings

- dated target snapshot archive is missing for this run
- etf coverage 0.0 < floor 0.3
- free_data_manifest is missing (latest_asof=)
- latest target date 2026-06-16 is after latest observable close 2026-06-12; freshness gate uses observable close
- macro freshness uses directory_mtime_proxy; add a macro latest_manifest.json/asof watermark
- sec_v1_evidence coverage 0.12012570548999486 < floor 0.2

## Watermarks

| source | status | latest_asof | age_days | cadence_days | owner |
| --- | --- | --- | ---: | ---: | --- |
| prices | ok | 2026-06-15 | 1.0 | 3 | free_data_daily_update.yml |
| macro | ok | 2026-06-16T15:23:11.824273+00:00 | 0.0 | 3 | daily_crisis_monitor.yml/free_data_daily_update.yml |
| sec_companyfacts | ok | 2026-06-16T11:41:21.876051+00:00 | 0.0 | 7 | data_readiness_preflight.yml/free_data_daily_update.yml |
| form4_transactions | ok | 2026-06-16T02:17:25.942000+00:00 | 0.0 | 5 | sec_form4_daily_refresh.yml |
| institutional_13f_holdings | ok | 2026-05-25T07:27:21.847000+00:00 | 22.0 | 100 | sec_13f_quarterly_refresh.yml |
| etf_holdings | ok | 2026-06-09T16:59:50.667000+00:00 | 7.0 | 40 | etf_holdings_monthly_refresh.yml |
| free_data_manifest | missing |  |  | 3 | free_data_daily_update.yml |

## Evidence Coverage

- `etf`: status `WARN`, coverage `0.0`, floor `0.3`
- `sec_v1_evidence`: status `WARN`, coverage `0.12012570548999486`, floor `0.2`
- `13f`: status `ok`, coverage `0.7781554643406875`, floor `0.5`
- `smart_money`: status `ok`, coverage `0.7323413716435779`, floor `0.5`
- `top_manager`: status `ok`, coverage `0.6860355737985292`, floor `0.05`
