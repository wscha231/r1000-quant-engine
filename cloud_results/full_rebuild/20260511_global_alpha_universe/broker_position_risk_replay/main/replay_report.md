# Broker Position-Risk Replay

Account-ledger conversion of monthly proxy risk rules.

- Portfolio: `main`
- Status: `completed`
- Metric mode: `broker_ledger_position_risk_next_close`
- CAGR: 13.84%
- Sharpe: 0.843
- MaxDD: -34.90%
- Avg cash: 17.58%
- Risk exits: 417
- Risk trims: 211
- Total trades: 3018
- Valid for production evidence: `true`

No forward-return labels are used for exit timing. Signals are detected from daily closes and filled at the next close.
