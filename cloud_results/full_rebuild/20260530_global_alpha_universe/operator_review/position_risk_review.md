# Position Risk Review

Research-only review of daily risk exits/trims against official broker-ledger base replay.

- Production activation allowed: `false`
- Official metric required: `broker_ledger_next_close`
- Challenger metric required: `broker_ledger_position_risk_next_close`

| Portfolio | Decision | Base CAGR | Risk CAGR | CAGR Delta | Base MDD | Risk MDD | MDD Improvement | Base Trades | Risk Trades | Risk Exits | Risk Trims |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| main | `REVIEW_REQUIRED` | 20.21% | 12.73% | -7.49% | -33.27% | -33.93% | -0.66% | 2,844 | 3,206 | 478 | 220 |
| concentrated | `REVIEW_REQUIRED` | 33.20% | 19.78% | -13.42% | -39.88% | -44.41% | -4.52% | 403 | 435 | 44 | 22 |

Rules:
- This file is operator review only; it is not a trade instruction.
- Passing this review does not activate production.
- Promotion still requires target gates, cost sensitivity, stress windows, and human approval.
