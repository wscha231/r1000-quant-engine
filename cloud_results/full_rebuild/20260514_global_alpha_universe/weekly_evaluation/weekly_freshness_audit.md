# Weekly Evaluation Freshness Audit

- status: `ok`
- latest_scored_date: `2026-05-14`
- primary_weekly_eval_date: `2026-05-13`
- scored_vs_weekly_eval_lag_days: `1`
- stale_days_threshold: `10`
- latest_raw_portfolio_cash_target: `0.0`
- latest_unified_cash_target: `0.2499999999999999`

## Portfolio Metrics

### main
- status: `completed`
- weeks: `413`
- range: `2019-05-03` -> `2026-05-13`
- CAGR: `0.22294000363752553`
- Sharpe: `1.109513389194434`
- MaxDD: `-0.2777586605840191`
- avg_cash_weight: `0.052906902842701976`

### concentrated
- status: `completed`
- weeks: `413`
- range: `2019-05-03` -> `2026-05-13`
- CAGR: `0.3553121540811017`
- Sharpe: `1.2185511223885324`
- MaxDD: `-0.40189334174619873`
- avg_cash_weight: `5.510792252982012e-17`

## Notes
- This sidecar does not alter production portfolio selection.
- Monthly backtest labels can lag because they need a next rebalance date to realize returns.
- A stale status means the engine needs true weekly scored snapshots, not just a display fix.
