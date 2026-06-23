# Execution Lag Review

Research-only review of whether account-aware execution replay reduces current/target drift, churn, or drawdown.

- Production activation allowed: `false`
- Official metric required: `broker_ledger_next_close`
- Cash policy flag: `below_combined_cash_target`

| Portfolio | Decision | Base CAGR | Exec CAGR | CAGR Delta | Base MDD | Exec MDD | MDD Improvement | Base Trades | Exec Trades | Preview Turnover | Current Cash | Projected Cash |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| main | `REVIEW_REQUIRED` | 35.02% | 33.17% | -1.85% | -26.03% | -33.29% | -7.26% | 1,647 | 925 | 22.63% | 14.63% | 19.14% |
| concentrated | `REVIEW_REQUIRED` | 45.96% | 43.50% | -2.46% | -24.60% | -33.01% | -8.41% | 586 | 390 | 26.18% | 5.54% | 7.73% |

Rules:
- This file is operator review only; it is not a trade instruction.
- `broker_ledger_execution_policy_next_close` is a research challenger metric, not the official production metric.
- Promotion still requires the official broker-ledger path, stress windows, cost sensitivity, and human approval.
