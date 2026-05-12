# Weekly Evaluation Freshness Audit

- status: `ok`
- latest_scored_date: `2026-05-12`
- primary_weekly_eval_date: `2026-05-08`
- scored_vs_weekly_eval_lag_days: `4`
- stale_days_threshold: `10`
- latest_raw_portfolio_cash_target: `0.0`
- latest_unified_cash_target: `0.2735559701222695`

## Portfolio Metrics

### main
- status: `completed`
- weeks: `412`
- range: `2019-05-03` -> `2026-05-08`
- CAGR: `0.20692023307529372`
- Sharpe: `1.0714815418014174`
- MaxDD: `-0.2731454621041076`
- avg_cash_weight: `0.05107340524624697`

### concentrated
- status: `completed`
- weeks: `412`
- range: `2019-05-03` -> `2026-05-08`
- CAGR: `0.3485263254264166`
- Sharpe: `1.2384018187977708`
- MaxDD: `-0.376065426164794`
- avg_cash_weight: `6.952367484303165e-17`

## Notes
- This sidecar does not alter production portfolio selection.
- Monthly backtest labels can lag because they need a next rebalance date to realize returns.
- A stale status means the engine needs true weekly scored snapshots, not just a display fix.
