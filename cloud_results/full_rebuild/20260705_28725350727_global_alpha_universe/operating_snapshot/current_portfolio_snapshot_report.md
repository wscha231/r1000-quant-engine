# Current Portfolio Snapshot

- Status: `completed`
- As-of date: `2026-07-02`
- Semantics: `current_broker_ledger_mark_to_market`
- Rows: 21
- Cash rows: 2
- Monster recommendation rows: 0
- Combined current cash: 14.95%
- Combined target cash: 14.80%
- Cash policy review: `HOLD`
- Primary user view: `current_operating_holdings_latest.csv`

This file answers what the simulated broker-ledger portfolios currently hold after historical trades and latest close mark-to-market.
It is different from `portfolio_latest.csv` and `concentrated_portfolio_latest.csv`, which are target recommendation books.
Use `proposed_target_deltas_latest.csv` only for review actions and target drift, not as current holdings.
Cash policy fields are combined-account context; they are not separate per-portfolio target cash weights.

## Portfolio Rows

- concentrated: 5 equity positions
- main: 14 equity positions
