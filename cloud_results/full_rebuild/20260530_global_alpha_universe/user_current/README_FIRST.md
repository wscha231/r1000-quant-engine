# README FIRST

This folder is the default user-facing operating view.

- `01_current_holdings.csv` is the current simulated broker-ledger book.
- `03_period_returns.csv` uses broker replay equity curves and includes drawdown.
- `04_official_metrics.json` is the official broker-ledger metric payload.
- `07_research_sidecar_context.json` explains which research-only sidecars did not alter current holdings.
- Target recommendation books are not current holdings and are hidden by default.
- Market Leader / Multi-Lane / Crisis sidecars are research-only unless explicitly promoted by `approved_integrated`.
- `outputs/operator_review/projected_holdings_after_integrated_target.csv` shows the shadow target delta when available.
- `outputs/operator_review/projected_holdings_after_market_leader_target.csv` shows the Market Leader shadow delta when available.
- `outputs/decision_cadence/decision_cadence_summary.json` explains daily/weekly/monthly review cadence and mid-month reentry rules when available.
- Deprecated/research backtests are not copied here and are not promotion evidence.
- Do not trade rows or portfolios marked REVIEW_REQUIRED or DO_NOT_TRADE.
