# Weekly Evaluation Freshness Audit

- status: `ok`
- latest_scored_date: `2026-05-11`
- primary_weekly_eval_date: `2026-05-08`
- scored_vs_weekly_eval_lag_days: `3`
- stale_days_threshold: `10`
- latest_raw_portfolio_cash_target: `0.0`
- latest_unified_cash_target: `0.30134441944809365`

## Portfolio Metrics

### main
- status: `completed`
- weeks: `527`
- range: `2017-06-02` -> `2026-05-08`
- CAGR: `0.17428727011603762`
- Sharpe: `0.922591874303147`
- MaxDD: `-0.320690685999228`
- avg_cash_weight: `0.03828034923338766`

### concentrated
- status: `completed`
- weeks: `527`
- range: `2017-06-02` -> `2026-05-08`
- CAGR: `0.2723868928563371`
- Sharpe: `1.0454268467162455`
- MaxDD: `-0.3996046764551485`
- avg_cash_weight: `5.730183352904034e-17`

## Notes
- This sidecar does not alter production portfolio selection.
- Monthly backtest labels can lag because they need a next rebalance date to realize returns.
- A stale status means the engine needs true weekly scored snapshots, not just a display fix.
