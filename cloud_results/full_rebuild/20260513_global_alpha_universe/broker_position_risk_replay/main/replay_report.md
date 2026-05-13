# Broker Position-Risk Replay

Account-ledger conversion of monthly proxy risk rules.

- Portfolio: `main`
- Status: `completed`
- Metric mode: `broker_ledger_position_risk_next_close`
- CAGR: 14.03%
- Sharpe: 0.848
- MaxDD: -34.46%
- Avg cash: 17.06%
- Risk exits: 334
- Risk trims: 166
- Total trades: 2382
- Valid for production evidence: `true`

No forward-return labels are used for exit timing. Signals are detected from daily closes and filled at the next close.
