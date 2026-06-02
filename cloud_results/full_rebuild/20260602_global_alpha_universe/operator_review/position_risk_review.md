# Position Risk Review

Research-only review of daily risk exits/trims against official broker-ledger base replay.

- Production activation allowed: `false`
- Official metric required: `broker_ledger_next_close`
- Challenger metric required: `broker_ledger_position_risk_next_close`

| Portfolio | Decision | Base CAGR | Risk CAGR | CAGR Delta | Base MDD | Risk MDD | MDD Improvement | Base Trades | Risk Trades | Risk Exits | Risk Trims |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| main | `REVIEW_REQUIRED` | 35.21% | 22.68% | -12.54% | -41.43% | -46.62% | -5.19% | 1,749 | 2,035 | 354 | 118 |
| concentrated | `REVIEW_REQUIRED` | 25.73% | 9.73% | -16.00% | -62.51% | -72.25% | -9.74% | 593 | 702 | 153 | 40 |

Rules:
- This file is operator review only; it is not a trade instruction.
- Passing this review does not activate production.
- Promotion still requires target gates, cost sensitivity, stress windows, and human approval.
