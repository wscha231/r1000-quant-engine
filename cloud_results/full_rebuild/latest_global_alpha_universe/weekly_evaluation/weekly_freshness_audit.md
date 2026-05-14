# Weekly Evaluation Freshness Audit

- status: `ok`
- latest_scored_date: `2026-05-15`
- primary_weekly_eval_date: `2026-05-14`
- scored_vs_weekly_eval_lag_days: `1`
- stale_days_threshold: `10`
- latest_raw_portfolio_cash_target: `0.0`
- latest_unified_cash_target: `0.30441611771819843`

## Portfolio Metrics

### main
- status: `completed`
- weeks: `413`
- range: `2019-05-03` -> `2026-05-14`
- CAGR: `0.2127844222660824`
- Sharpe: `1.0473922069616761`
- MaxDD: `-0.3141586354184335`
- avg_cash_weight: `0.052550774313278016`

### concentrated
- status: `completed`
- weeks: `413`
- range: `2019-05-03` -> `2026-05-14`
- CAGR: `0.3551167590645685`
- Sharpe: `1.2487983288548905`
- MaxDD: `-0.4165655356369631`
- avg_cash_weight: `6.532304963290873e-17`

## Notes
- This sidecar does not alter production portfolio selection.
- Monthly backtest labels can lag because they need a next rebalance date to realize returns.
- A stale status means the engine needs true weekly scored snapshots, not just a display fix.
