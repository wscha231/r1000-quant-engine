# Weekly Evaluation Freshness Audit

- status: `ok`
- latest_scored_date: `2026-05-13`
- primary_weekly_eval_date: `2026-05-12`
- scored_vs_weekly_eval_lag_days: `1`
- stale_days_threshold: `10`
- latest_raw_portfolio_cash_target: `0.0`
- latest_unified_cash_target: `0.28777706389406765`

## Portfolio Metrics

### main
- status: `completed`
- weeks: `413`
- range: `2019-05-03` -> `2026-05-12`
- CAGR: `0.2035140406347009`
- Sharpe: `1.0671105876057099`
- MaxDD: `-0.3063451836641502`
- avg_cash_weight: `0.05333878899110984`

### concentrated
- status: `completed`
- weeks: `413`
- range: `2019-05-03` -> `2026-05-12`
- CAGR: `0.3712525650284637`
- Sharpe: `1.3057155486036582`
- MaxDD: `-0.3757205186218061`
- avg_cash_weight: `5.860257127561359e-17`

## Notes
- This sidecar does not alter production portfolio selection.
- Monthly backtest labels can lag because they need a next rebalance date to realize returns.
- A stale status means the engine needs true weekly scored snapshots, not just a display fix.
