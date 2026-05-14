# Broker Position-Risk Replay

Account-ledger conversion of monthly proxy risk rules.

- Portfolio: `main`
- Status: `completed`
- Metric mode: `broker_ledger_position_risk_next_close`
- CAGR: 13.55%
- Sharpe: 0.863
- MaxDD: -32.09%
- Avg cash: 25.89%
- Risk exits: 451
- Risk trims: 231
- Total trades: 3166
- Valid for production evidence: `true`

No forward-return labels are used for exit timing. Signals are detected from daily closes and filled at the next close.
