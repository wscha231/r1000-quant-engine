# Weekly Evaluation Freshness Audit

- status: `ok`
- latest_scored_date: `2026-05-08`
- primary_weekly_eval_date: `2026-05-08`
- scored_vs_weekly_eval_lag_days: `0`
- stale_days_threshold: `10`
- latest_raw_portfolio_cash_target: `0.0`
- latest_unified_cash_target: `0.28410567956869004`

## Portfolio Metrics

### main
- status: `completed`
- weeks: `412`
- range: `2019-05-03` -> `2026-05-08`
- CAGR: `0.20089645943802514`
- Sharpe: `0.972990913249699`
- MaxDD: `-0.3471267101694868`
- avg_cash_weight: `0.050615732235846526`

### concentrated
- status: `completed`
- weeks: `412`
- range: `2019-05-03` -> `2026-05-08`
- CAGR: `0.3555259820579093`
- Sharpe: `1.1959586308077232`
- MaxDD: `-0.4052693821843961`
- avg_cash_weight: `6.063111178171364e-17`

## Notes
- This sidecar does not alter production portfolio selection.
- Monthly backtest labels can lag because they need a next rebalance date to realize returns.
- A stale status means the engine needs true weekly scored snapshots, not just a display fix.
