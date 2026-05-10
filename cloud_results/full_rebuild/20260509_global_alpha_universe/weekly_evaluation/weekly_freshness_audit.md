# Weekly Evaluation Freshness Audit

- status: `ok`
- latest_scored_date: `2026-05-08`
- primary_weekly_eval_date: `2026-05-08`
- scored_vs_weekly_eval_lag_days: `0`
- stale_days_threshold: `10`
- latest_raw_portfolio_cash_target: `0.0`
- latest_unified_cash_target: `0.3193791142341008`

## Portfolio Metrics

### main
- status: `completed`
- weeks: `412`
- range: `2019-05-03` -> `2026-05-08`
- CAGR: `0.19293276674856497`
- Sharpe: `0.9939056990151492`
- MaxDD: `-0.33021718741017314`
- avg_cash_weight: `0.04912832759807209`

### concentrated
- status: `completed`
- weeks: `412`
- range: `2019-05-03` -> `2026-05-08`
- CAGR: `0.3641044068324517`
- Sharpe: `1.3005416480497822`
- MaxDD: `-0.3615462374291999`
- avg_cash_weight: `6.844578841135673e-17`

## Notes
- This sidecar does not alter production portfolio selection.
- Monthly backtest labels can lag because they need a next rebalance date to realize returns.
- A stale status means the engine needs true weekly scored snapshots, not just a display fix.
