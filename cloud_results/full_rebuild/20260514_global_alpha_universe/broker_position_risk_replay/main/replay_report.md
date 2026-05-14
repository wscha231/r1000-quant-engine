# Broker Position-Risk Replay

Account-ledger conversion of monthly proxy risk rules.

- Portfolio: `main`
- Status: `completed`
- Metric mode: `broker_ledger_position_risk_next_close`
- CAGR: 15.42%
- Sharpe: 0.914
- MaxDD: -31.54%
- Avg cash: 17.40%
- Risk exits: 441
- Risk trims: 231
- Total trades: 3097
- Valid for production evidence: `true`

No forward-return labels are used for exit timing. Signals are detected from daily closes and filled at the next close.
