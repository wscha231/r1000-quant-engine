# Weekly Evaluation Freshness Audit

- status: `ok`
- latest_scored_date: `2026-05-08`
- primary_weekly_eval_date: `2026-05-08`
- scored_vs_weekly_eval_lag_days: `0`
- stale_days_threshold: `10`
- latest_raw_portfolio_cash_target: `0.0`
- latest_unified_cash_target: `0.2759999999999999`

## Portfolio Metrics

### main
- status: `completed`
- weeks: `412`
- range: `2019-05-03` -> `2026-05-08`
- CAGR: `0.19716264232217395`
- Sharpe: `1.0076349864247922`
- MaxDD: `-0.30406314509390353`
- avg_cash_weight: `0.04523346283427704`

### concentrated
- status: `completed`
- weeks: `412`
- range: `2019-05-03` -> `2026-05-08`
- CAGR: `0.33025125872465155`
- Sharpe: `1.182764124709736`
- MaxDD: `-0.3996628378892775`
- avg_cash_weight: `6.41342426846571e-17`

## Notes
- This sidecar does not alter production portfolio selection.
- Monthly backtest labels can lag because they need a next rebalance date to realize returns.
- A stale status means the engine needs true weekly scored snapshots, not just a display fix.
