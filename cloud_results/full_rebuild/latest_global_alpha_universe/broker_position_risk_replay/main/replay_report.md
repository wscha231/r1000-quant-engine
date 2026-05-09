# Broker Position-Risk Replay

Account-ledger conversion of monthly proxy risk rules.

- Portfolio: `main`
- Status: `completed`
- Metric mode: `broker_ledger_position_risk_next_close`
- CAGR: 13.40%
- Sharpe: 0.821
- MaxDD: -33.79%
- Avg cash: 17.11%
- Risk exits: 416
- Risk trims: 213
- Total trades: 2980
- Valid for production evidence: `true`

No forward-return labels are used for exit timing. Signals are detected from daily closes and filled at the next close.
