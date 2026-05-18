# Broker Position-Risk Replay

Account-ledger conversion of monthly proxy risk rules.

- Portfolio: `main`
- Status: `completed`
- Metric mode: `broker_ledger_position_risk_next_close`
- CAGR: 11.54%
- Sharpe: 0.603
- MaxDD: -30.84%
- Avg cash: 26.17%
- Risk exits: 447
- Risk trims: 226
- Total trades: 3204
- Valid for production evidence: `true`

No forward-return labels are used for exit timing. Signals are detected from daily closes and filled at the next close.
