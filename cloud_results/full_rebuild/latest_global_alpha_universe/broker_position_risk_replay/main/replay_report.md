# Broker Position-Risk Replay

Account-ledger conversion of monthly proxy risk rules.

- Portfolio: `main`
- Status: `completed`
- Metric mode: `broker_ledger_position_risk_next_close`
- CAGR: 13.08%
- Sharpe: 0.687
- MaxDD: -31.28%
- Avg cash: 25.78%
- Risk exits: 454
- Risk trims: 237
- Total trades: 3181
- Valid for production evidence: `true`

No forward-return labels are used for exit timing. Signals are detected from daily closes and filled at the next close.
