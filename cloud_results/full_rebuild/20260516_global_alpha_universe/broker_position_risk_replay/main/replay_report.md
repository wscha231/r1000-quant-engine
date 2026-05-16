# Broker Position-Risk Replay

Account-ledger conversion of monthly proxy risk rules.

- Portfolio: `main`
- Status: `completed`
- Metric mode: `broker_ledger_position_risk_next_close`
- CAGR: 6.87%
- Sharpe: 0.356
- MaxDD: -28.36%
- Avg cash: 16.83%
- Risk exits: 378
- Risk trims: 217
- Total trades: 2920
- Valid for production evidence: `true`

No forward-return labels are used for exit timing. Signals are detected from daily closes and filled at the next close.
