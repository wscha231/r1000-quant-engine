# Market Leader Concentration Challenger

Research-only sidecar. It rebuilds monthly target books from the historical candidate book and replays them through broker-ledger next-close.

- Status: `completed`
- Candidate source: `explicit`
- Promotion evaluation: `research_only_no_baseline_lock`
- Production activation allowed: `false`

## Default Variants

- Main `main_N18_cap12_sub40_theme60_risk`: CAGR 34.93%, MDD -32.60%, Sharpe 1.214, mode `broker_ledger_next_close`
- Concentrated `concentrated_N5_cap30_sub70_risk`: CAGR 28.98%, MDD -49.87%, Sharpe 0.888, mode `broker_ledger_next_close`

Rules:
- Latest-only rankings are blocked from producing broker metrics.
- Missing 13F/Form4/ETF evidence lowers confidence only; it is not a quality penalty.
- Production defaults, feature store, and live target books are unchanged.
