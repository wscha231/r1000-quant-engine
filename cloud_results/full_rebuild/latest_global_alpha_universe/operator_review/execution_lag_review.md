# Execution Lag Review

Research-only review of whether account-aware execution replay reduces current/target drift, churn, or drawdown.

- Production activation allowed: `false`
- Official metric required: `broker_ledger_next_close`
- Cash policy flag: `cash_close_to_target`

| Portfolio | Decision | Base CAGR | Exec CAGR | CAGR Delta | Base MDD | Exec MDD | MDD Improvement | Base Trades | Exec Trades | Preview Turnover | Current Cash | Projected Cash |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| main | `REVIEW_REQUIRED` | 32.94% | 32.34% | -0.60% | -25.65% | -28.89% | -3.23% | 1,612 | 969 | 11.00% | 11.03% | 10.65% |
| concentrated | `REVIEW_REQUIRED` | 46.99% | 41.24% | -5.75% | -23.22% | -33.38% | -10.16% | 724 | 419 | 2.50% | 16.88% | 16.69% |

Rules:
- This file is operator review only; it is not a trade instruction.
- `broker_ledger_execution_policy_next_close` is a research challenger metric, not the official production metric.
- Promotion still requires the official broker-ledger path, stress windows, cost sensitivity, and human approval.
