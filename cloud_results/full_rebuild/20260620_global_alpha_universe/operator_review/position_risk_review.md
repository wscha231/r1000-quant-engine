# Position Risk Review

Research-only review of daily risk exits/trims against official broker-ledger base replay.

- Production activation allowed: `false`
- Official metric required: `broker_ledger_next_close`
- Challenger metric required: `broker_ledger_position_risk_next_close`

| Portfolio | Decision | Base CAGR | Risk CAGR | CAGR Delta | Base MDD | Risk MDD | MDD Improvement | Base Trades | Risk Trades | Risk Exits | Risk Trims |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| main | `DO_NOT_USE` | 34.73% | 29.88% | -4.85% | -26.05% | -25.82% | 0.24% | 1,657 | 1,793 | 194 | 56 |
| concentrated | `DO_NOT_USE` | 45.47% | 30.93% | -14.55% | -24.59% | -27.78% | -3.19% | 589 | 654 | 84 | 30 |

Rules:
- This file is operator review only; it is not a trade instruction.
- Passing this review does not activate production.
- Promotion still requires target gates, cost sensitivity, stress windows, and human approval.
