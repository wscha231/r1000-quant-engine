# Broker Position-Risk Replay

Account-ledger conversion of monthly proxy risk rules.

- Portfolio: `main`
- Status: `completed`
- Metric mode: `broker_ledger_position_risk_next_close`
- CAGR: 14.47%
- Sharpe: 0.858
- MaxDD: -34.39%
- Avg cash: 16.61%
- Risk exits: 427
- Risk trims: 210
- Total trades: 3009
- Valid for production evidence: `true`

No forward-return labels are used for exit timing. Signals are detected from daily closes and filled at the next close.
