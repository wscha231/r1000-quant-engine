# Execution Lag Review

Research-only review of whether account-aware execution replay reduces current/target drift, churn, or drawdown.

- Production activation allowed: `false`
- Official metric required: `broker_ledger_next_close`
- Cash policy flag: `cash_above_target`

| Portfolio | Decision | Base CAGR | Exec CAGR | CAGR Delta | Base MDD | Exec MDD | MDD Improvement | Base Trades | Exec Trades | Preview Turnover | Current Cash | Projected Cash |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| main | `REVIEW_REQUIRED` | 20.21% | 19.13% | -1.08% | -33.27% | -34.86% | -1.60% | 2,844 | 1,016 | 153.48% | 24.33% | 4.23% |
| concentrated | `REVIEW_REQUIRED` | 33.20% | 30.35% | -2.85% | -39.88% | -37.50% | 2.38% | 403 | 272 | 199.45% | 0.00% | 0.06% |

Rules:
- This file is operator review only; it is not a trade instruction.
- `broker_ledger_execution_policy_next_close` is a research challenger metric, not the official production metric.
- Promotion still requires the official broker-ledger path, stress windows, cost sensitivity, and human approval.
