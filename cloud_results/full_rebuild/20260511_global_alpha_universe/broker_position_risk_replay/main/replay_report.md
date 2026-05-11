# Broker Position-Risk Replay

Account-ledger conversion of monthly proxy risk rules.

- Portfolio: `main`
- Status: `completed`
- Metric mode: `broker_ledger_position_risk_next_close`
- CAGR: 12.04%
- Sharpe: 0.747
- MaxDD: -34.66%
- Avg cash: 15.73%
- Risk exits: 522
- Risk trims: 257
- Total trades: 3773
- Valid for production evidence: `true`

No forward-return labels are used for exit timing. Signals are detected from daily closes and filled at the next close.
