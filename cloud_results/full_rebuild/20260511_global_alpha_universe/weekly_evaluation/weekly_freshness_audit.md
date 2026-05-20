# Weekly Evaluation Freshness Audit

- status: `ok`
- latest_scored_date: `2026-05-11`
- primary_weekly_eval_date: `2026-05-08`
- scored_vs_weekly_eval_lag_days: `3`
- stale_days_threshold: `10`
- latest_raw_portfolio_cash_target: `0.0`
- latest_unified_cash_target: `0.2733611546477489`

## Portfolio Metrics

### main
- status: `completed`
- weeks: `412`
- range: `2019-05-03` -> `2026-05-08`
- CAGR: `0.20791753628055742`
- Sharpe: `1.0564476992657847`
- MaxDD: `-0.2874788031627036`
- avg_cash_weight: `0.04875671484995649`

### concentrated
- status: `completed`
- weeks: `412`
- range: `2019-05-03` -> `2026-05-08`
- CAGR: `0.33323425448389243`
- Sharpe: `1.1957080537034912`
- MaxDD: `-0.3989840780351398`
- avg_cash_weight: `6.871526001927546e-17`

## Notes
- This sidecar does not alter production portfolio selection.
- Monthly backtest labels can lag because they need a next rebalance date to realize returns.
- A stale status means the engine needs true weekly scored snapshots, not just a display fix.
