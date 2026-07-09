# Forward Estimate Shard 000 Result

## Verdict

Workflow run `29015925250` succeeded, but free-vendor estimate coverage was too
low to use as a Concentrated strengthening signal.

This is a data entitlement / coverage result, not an alpha result.

## Result

- run conclusion: `success`
- collector status: `blocked_partial_coverage`
- collector reason: `coverage_below_80pct_warn_only`
- requested tickers: 50
- snapshot rows: 36
- rows with true forward estimates: 2
- estimate coverage ratio: 4%
- tickers with true forward estimates: `AAPL`, `ADBE`
- fetch sources: `fmp`, `finnhub`
- vendor blocked errors present: `true`

## Safety

- fullrun dispatched: `false`
- backtest acceptance allowed: `false`
- production activation allowed: `false`
- live trading enabled: `false`
- raw known-secret fragment scan: clean
- persisted vendor URL credentials were masked as `apikey=***` and `token=***`

## Interpretation

The broad-universe scan path works mechanically. The current free FMP/Finnhub
entitlement does not provide enough forward-estimate coverage on this shard.

Do not turn this into a stock-level negative signal. Missing coverage is
neutral. The next useful action is either:

- continue slow shard coverage measurement to quantify free-vendor coverage, or
- obtain a higher-entitlement / PIT estimates vendor before trying to use
estimate revisions as a historical CAGR/MDD lever.
