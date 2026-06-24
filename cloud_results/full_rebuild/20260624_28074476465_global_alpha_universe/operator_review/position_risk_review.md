# Position Risk Review

Research-only review of daily risk exits/trims against official broker-ledger base replay.

- Production activation allowed: `false`
- Official metric required: `broker_ledger_next_close`
- Challenger metric required: `broker_ledger_position_risk_next_close`

| Portfolio | Decision | Base CAGR | Risk CAGR | CAGR Delta | Base MDD | Risk MDD | MDD Improvement | Base Trades | Risk Trades | Risk Exits | Risk Trims |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| main | `DO_NOT_USE` | 33.15% | 28.66% | -4.49% | -26.02% | -25.77% | 0.25% | 1,681 | 1,821 | 196 | 59 |
| concentrated | `DO_NOT_USE` | 46.24% | 31.76% | -14.48% | -25.82% | -28.08% | -2.26% | 597 | 660 | 85 | 29 |

Rules:
- This file is operator review only; it is not a trade instruction.
- Passing this review does not activate production.
- Promotion still requires target gates, cost sensitivity, stress windows, and human approval.
