# Position Risk Review

Research-only review of daily risk exits/trims against official broker-ledger base replay.

- Production activation allowed: `false`
- Official metric required: `broker_ledger_next_close`
- Challenger metric required: `broker_ledger_position_risk_next_close`

| Portfolio | Decision | Base CAGR | Risk CAGR | CAGR Delta | Base MDD | Risk MDD | MDD Improvement | Base Trades | Risk Trades | Risk Exits | Risk Trims |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| main | `DO_NOT_USE` | 35.02% | 30.26% | -4.77% | -26.03% | -26.53% | -0.50% | 1,647 | 1,788 | 195 | 60 |
| concentrated | `DO_NOT_USE` | 45.96% | 31.17% | -14.79% | -24.60% | -27.99% | -3.39% | 586 | 651 | 84 | 30 |

Rules:
- This file is operator review only; it is not a trade instruction.
- Passing this review does not activate production.
- Promotion still requires target gates, cost sensitivity, stress windows, and human approval.
