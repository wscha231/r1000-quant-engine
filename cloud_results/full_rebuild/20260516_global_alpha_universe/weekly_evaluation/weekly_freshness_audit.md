# Weekly Evaluation Freshness Audit

- status: `ok`
- latest_scored_date: `2026-05-15`
- primary_weekly_eval_date: `2026-05-15`
- scored_vs_weekly_eval_lag_days: `0`
- stale_days_threshold: `10`
- latest_raw_portfolio_cash_target: `0.0`
- latest_unified_cash_target: `0.2499999999999999`

## Portfolio Metrics

### main
- status: `completed`
- weeks: `408`
- range: `2019-06-07` -> `2026-05-15`
- CAGR: `0.13607771972101546`
- Sharpe: `0.8336985822157801`
- MaxDD: `-0.2538546442074615`
- avg_cash_weight: `0.051920060632480336`

### concentrated
- status: `completed`
- weeks: `408`
- range: `2019-06-07` -> `2026-05-15`
- CAGR: `0.1632103366909008`
- Sharpe: `0.7821568671362448`
- MaxDD: `-0.32030285484394894`
- avg_cash_weight: `4.8708314070564465e-17`

## Notes
- This sidecar does not alter production portfolio selection.
- Monthly backtest labels can lag because they need a next rebalance date to realize returns.
- A stale status means the engine needs true weekly scored snapshots, not just a display fix.
