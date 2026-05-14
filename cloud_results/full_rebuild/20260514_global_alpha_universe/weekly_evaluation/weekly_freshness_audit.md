# Weekly Evaluation Freshness Audit

- status: `ok`
- latest_scored_date: `2026-05-14`
- primary_weekly_eval_date: `2026-05-13`
- scored_vs_weekly_eval_lag_days: `1`
- stale_days_threshold: `10`
- latest_raw_portfolio_cash_target: `0.0`
- latest_unified_cash_target: `0.2903405562560911`

## Portfolio Metrics

### main
- status: `completed`
- weeks: `413`
- range: `2019-05-03` -> `2026-05-13`
- CAGR: `0.2212372181129254`
- Sharpe: `1.0820437908976164`
- MaxDD: `-0.30986905360997796`
- avg_cash_weight: `0.052771867084280784`

### concentrated
- status: `completed`
- weeks: `413`
- range: `2019-05-03` -> `2026-05-13`
- CAGR: `0.36397026415700107`
- Sharpe: `1.2412175032665036`
- MaxDD: `-0.41691743718925756`
- avg_cash_weight: `7.204352799020386e-17`

## Notes
- This sidecar does not alter production portfolio selection.
- Monthly backtest labels can lag because they need a next rebalance date to realize returns.
- A stale status means the engine needs true weekly scored snapshots, not just a display fix.
