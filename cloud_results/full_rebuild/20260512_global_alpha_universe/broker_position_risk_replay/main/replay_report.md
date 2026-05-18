# Broker Position-Risk Replay

Account-ledger conversion of monthly proxy risk rules.

- Portfolio: `main`
- Status: `completed`
- Metric mode: `broker_ledger_position_risk_next_close`
- CAGR: 13.28%
- Sharpe: 0.818
- MaxDD: -33.73%
- Avg cash: 17.77%
- Risk exits: 457
- Risk trims: 223
- Total trades: 3119
- Valid for production evidence: `true`

No forward-return labels are used for exit timing. Signals are detected from daily closes and filled at the next close.
