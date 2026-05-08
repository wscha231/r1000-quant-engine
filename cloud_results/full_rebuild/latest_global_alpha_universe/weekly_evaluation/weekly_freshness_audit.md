# Weekly Evaluation Freshness Audit

- status: `stale`
- latest_scored_date: `2026-05-08`
- primary_weekly_eval_date: `2026-03-31`
- scored_vs_weekly_eval_lag_days: `38`
- stale_days_threshold: `10`

## Portfolio Metrics

### main
- status: `completed`
- weeks: `407`
- range: `2019-05-03` -> `2026-03-31`
- CAGR: `0.17842801306271916`
- Sharpe: `0.934797881618496`
- MaxDD: `-0.2874065306075805`
- avg_cash_weight: `0.0427533749224785`

### concentrated
- status: `completed`
- weeks: `407`
- range: `2019-05-03` -> `2026-03-31`
- CAGR: `6.201584246436511e+18`
- Sharpe: `3.6307625132370682`
- MaxDD: `-0.2484964460282978`
- avg_cash_weight: `0.40625509949709926`

## Notes
- This sidecar does not alter production portfolio selection.
- Monthly backtest labels can lag because they need a next rebalance date to realize returns.
- A stale status means the engine needs true weekly scored snapshots, not just a display fix.
