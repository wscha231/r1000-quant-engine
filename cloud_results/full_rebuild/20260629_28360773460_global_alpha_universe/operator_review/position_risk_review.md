# Position Risk Review

Research-only review of daily risk exits/trims against official broker-ledger base replay.

- Production activation allowed: `false`
- Official metric required: `broker_ledger_next_close`
- Challenger metric required: `broker_ledger_position_risk_next_close`

| Portfolio | Decision | Base CAGR | Risk CAGR | CAGR Delta | Base MDD | Risk MDD | MDD Improvement | Base Trades | Risk Trades | Risk Exits | Risk Trims |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| main | `DO_NOT_USE` | 35.28% | 30.82% | -4.45% | -24.25% | -25.19% | -0.94% | 1,679 | 1,812 | 195 | 55 |
| concentrated | `DO_NOT_USE` | 46.66% | 32.94% | -13.71% | -24.12% | -26.33% | -2.21% | 672 | 735 | 88 | 29 |

Rules:
- This file is operator review only; it is not a trade instruction.
- Passing this review does not activate production.
- Promotion still requires target gates, cost sensitivity, stress windows, and human approval.
