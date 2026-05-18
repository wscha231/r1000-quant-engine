# 10-Year Backtest Readiness

- Status: `not_ready`
- Min years: `9.8`
- PIT label: `None`
- Coverage readiness: `None`

## Price Cache

- Range: `None` to `None`
- Effective files: `866` / required `0`
- 10-year ready: `False`

## Target Books

- Main: `2019-05-31` to `2026-02-27`, rows `1977`
- Concentrated: `2019-05-31` to `2026-02-27`, rows `22908`
- 10-year ready: `False`

## Broker Replay

- Main: `2019-06-03` to `2026-05-15`, CAGR `0.1286319220673693`
- Concentrated: `2019-06-03` to `2026-05-15`, CAGR `0.16889553858006412`
- 10-year ready: `False`

## Blockers

- 10-year price cache/manifest is not ready for proxy replay
- monthly target books do not cover the requested 10-year window
- broker-ledger official replay does not yet cover the requested 10-year window

## Warnings

- SEC companyfacts archive is not available under data_raw/free/sec
- universe is labeled proxy, not PIT-safe official Russell 1000 history

## Next Actions

- Run free_data_lake_bootstrap.yml with price_mode=target_books and max_price_tickers=0.
- Restore or copy companyfacts.zip into data_raw/free/sec/companyfacts.zip, or run with sec_companyfacts=true.
- After 10-year target books exist, rerun broker-ledger replay and account evaluation.
