# Forward Estimate Universe Scan Plan

## Verdict

Use this as a forward-only archive plan. It does not change historical 7Y CAGR/MDD evidence, does not dispatch a fullrun, and does not enable production.

## Summary

- status: `ready_for_forward_archive_dispatch`
- ticker_count: 858
- shard_size: 50
- shard_count: 18
- vendor_order: `fmp,finnhub`
- workflow: `earnings_estimates_daily.yml`
- backtest_acceptance_allowed: `false`
- production_activation_allowed: `false`
- live_trading_enabled: `false`

## Leakage Contract

- `available_from` must remain the workflow fetch date.
- Missing vendor coverage is neutral, not a reject signal.
- Current/free estimate snapshots are forward paper-ledger evidence only.
- Historical CAGR/MDD claims still require PIT estimate history or another PIT-safe source.
- Alpha Vantage remains out of the default vendor order until key rotation is confirmed.

## Shards

| shard | tickers | csv | txt |
|---:|---:|---|---|
| shard_000 | 50 | `outputs\forward_estimate_universe_plan_20260709\shards\shard_000.csv` | `outputs\forward_estimate_universe_plan_20260709\shards\shard_000.txt` |
| shard_001 | 50 | `outputs\forward_estimate_universe_plan_20260709\shards\shard_001.csv` | `outputs\forward_estimate_universe_plan_20260709\shards\shard_001.txt` |
| shard_002 | 50 | `outputs\forward_estimate_universe_plan_20260709\shards\shard_002.csv` | `outputs\forward_estimate_universe_plan_20260709\shards\shard_002.txt` |
| shard_003 | 50 | `outputs\forward_estimate_universe_plan_20260709\shards\shard_003.csv` | `outputs\forward_estimate_universe_plan_20260709\shards\shard_003.txt` |
| shard_004 | 50 | `outputs\forward_estimate_universe_plan_20260709\shards\shard_004.csv` | `outputs\forward_estimate_universe_plan_20260709\shards\shard_004.txt` |
| shard_005 | 50 | `outputs\forward_estimate_universe_plan_20260709\shards\shard_005.csv` | `outputs\forward_estimate_universe_plan_20260709\shards\shard_005.txt` |
| shard_006 | 50 | `outputs\forward_estimate_universe_plan_20260709\shards\shard_006.csv` | `outputs\forward_estimate_universe_plan_20260709\shards\shard_006.txt` |
| shard_007 | 50 | `outputs\forward_estimate_universe_plan_20260709\shards\shard_007.csv` | `outputs\forward_estimate_universe_plan_20260709\shards\shard_007.txt` |
| shard_008 | 50 | `outputs\forward_estimate_universe_plan_20260709\shards\shard_008.csv` | `outputs\forward_estimate_universe_plan_20260709\shards\shard_008.txt` |
| shard_009 | 50 | `outputs\forward_estimate_universe_plan_20260709\shards\shard_009.csv` | `outputs\forward_estimate_universe_plan_20260709\shards\shard_009.txt` |
| shard_010 | 50 | `outputs\forward_estimate_universe_plan_20260709\shards\shard_010.csv` | `outputs\forward_estimate_universe_plan_20260709\shards\shard_010.txt` |
| shard_011 | 50 | `outputs\forward_estimate_universe_plan_20260709\shards\shard_011.csv` | `outputs\forward_estimate_universe_plan_20260709\shards\shard_011.txt` |
| shard_012 | 50 | `outputs\forward_estimate_universe_plan_20260709\shards\shard_012.csv` | `outputs\forward_estimate_universe_plan_20260709\shards\shard_012.txt` |
| shard_013 | 50 | `outputs\forward_estimate_universe_plan_20260709\shards\shard_013.csv` | `outputs\forward_estimate_universe_plan_20260709\shards\shard_013.txt` |
| shard_014 | 50 | `outputs\forward_estimate_universe_plan_20260709\shards\shard_014.csv` | `outputs\forward_estimate_universe_plan_20260709\shards\shard_014.txt` |
| shard_015 | 50 | `outputs\forward_estimate_universe_plan_20260709\shards\shard_015.csv` | `outputs\forward_estimate_universe_plan_20260709\shards\shard_015.txt` |
| shard_016 | 50 | `outputs\forward_estimate_universe_plan_20260709\shards\shard_016.csv` | `outputs\forward_estimate_universe_plan_20260709\shards\shard_016.txt` |
| shard_017 | 8 | `outputs\forward_estimate_universe_plan_20260709\shards\shard_017.csv` | `outputs\forward_estimate_universe_plan_20260709\shards\shard_017.txt` |

## Dispatch

Run shards gradually because free vendor coverage and rate limits are uncertain. Inspect `summary.json` and `collector.log` for redacted errors after each run.
