# Broker Position-Risk Replay

Account-ledger conversion of monthly proxy risk rules.

- Portfolio: `main`
- Status: `completed`
- Metric mode: `broker_ledger_position_risk_next_close`
- CAGR: 13.31%
- Sharpe: 0.811
- MaxDD: -34.50%
- Avg cash: 17.23%
- Risk exits: 347
- Risk trims: 179
- Total trades: 2411
- Valid for production evidence: `true`

No forward-return labels are used for exit timing. Signals are detected from daily closes and filled at the next close.
