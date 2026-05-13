# Weekly Evaluation Freshness Audit

- status: `ok`
- latest_scored_date: `2026-05-13`
- primary_weekly_eval_date: `2026-05-12`
- scored_vs_weekly_eval_lag_days: `1`
- stale_days_threshold: `10`
- latest_raw_portfolio_cash_target: `0.0`
- latest_unified_cash_target: `0.30767474582037857`

## Portfolio Metrics

### main
- status: `completed`
- weeks: `413`
- range: `2019-05-03` -> `2026-05-12`
- CAGR: `0.21025760518190628`
- Sharpe: `1.0690569816489162`
- MaxDD: `-0.30278480495342597`
- avg_cash_weight: `0.052541391444889556`

### concentrated
- status: `completed`
- weeks: `413`
- range: `2019-05-03` -> `2026-05-12`
- CAGR: `0.3504624627409627`
- Sharpe: `1.2488872655876866`
- MaxDD: `-0.3977784260620083`
- avg_cash_weight: `6.209722002140706e-17`

## Notes
- This sidecar does not alter production portfolio selection.
- Monthly backtest labels can lag because they need a next rebalance date to realize returns.
- A stale status means the engine needs true weekly scored snapshots, not just a display fix.
