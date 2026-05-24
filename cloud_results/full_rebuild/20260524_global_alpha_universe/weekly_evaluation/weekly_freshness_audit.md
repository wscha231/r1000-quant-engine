# Weekly Evaluation Freshness Audit

- status: `ok`
- latest_scored_date: `2026-05-22`
- primary_weekly_eval_date: `2026-05-22`
- scored_vs_weekly_eval_lag_days: `0`
- stale_days_threshold: `10`
- latest_raw_portfolio_cash_target: `0.0`
- latest_unified_cash_target: `0.33459328028629043`

## Portfolio Metrics

### main
- status: `completed`
- weeks: `409`
- range: `2019-06-07` -> `2026-05-22`
- CAGR: `0.20989689295893865`
- Sharpe: `1.08549695184095`
- MaxDD: `-0.2823745211770563`
- avg_cash_weight: `0.052713922060490685`

### concentrated
- status: `completed`
- weeks: `409`
- range: `2019-06-07` -> `2026-05-22`
- CAGR: `0.3594519203311548`
- Sharpe: `1.2270739761117038`
- MaxDD: `-0.3928073759423395`
- avg_cash_weight: `7.084797296507723e-17`

## Notes
- This sidecar does not alter production portfolio selection.
- Monthly backtest labels can lag because they need a next rebalance date to realize returns.
- A stale status means the engine needs true weekly scored snapshots, not just a display fix.
