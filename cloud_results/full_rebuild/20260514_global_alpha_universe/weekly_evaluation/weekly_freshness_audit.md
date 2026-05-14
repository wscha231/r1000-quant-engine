# Weekly Evaluation Freshness Audit

- status: `ok`
- latest_scored_date: `2026-05-14`
- primary_weekly_eval_date: `2026-05-13`
- scored_vs_weekly_eval_lag_days: `1`
- stale_days_threshold: `10`
- latest_raw_portfolio_cash_target: `0.0`
- latest_unified_cash_target: `0.32341833508956797`

## Portfolio Metrics

### main
- status: `completed`
- weeks: `413`
- range: `2019-05-03` -> `2026-05-13`
- CAGR: `0.22057450320343075`
- Sharpe: `1.0902476182536451`
- MaxDD: `-0.3159814786075399`
- avg_cash_weight: `0.052744487910302076`

### concentrated
- status: `completed`
- weeks: `413`
- range: `2019-05-03` -> `2026-05-13`
- CAGR: `0.3338102331732866`
- Sharpe: `1.179650301766003`
- MaxDD: `-0.4025951116974581`
- avg_cash_weight: `5.940902867848901e-17`

## Notes
- This sidecar does not alter production portfolio selection.
- Monthly backtest labels can lag because they need a next rebalance date to realize returns.
- A stale status means the engine needs true weekly scored snapshots, not just a display fix.
