# Execution Lag Review

Research-only review of whether account-aware execution replay reduces current/target drift, churn, or drawdown.

- Production activation allowed: `false`
- Official metric required: `broker_ledger_next_close`
- Cash policy flag: `below_combined_cash_target`

| Portfolio | Decision | Base CAGR | Exec CAGR | CAGR Delta | Base MDD | Exec MDD | MDD Improvement | Base Trades | Exec Trades | Preview Turnover | Current Cash | Projected Cash |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| main | `REVIEW_REQUIRED` | 33.15% | 34.27% | 1.12% | -26.02% | -35.82% | -9.81% | 1,681 | 930 | 18.88% | 15.67% | 19.22% |
| concentrated | `REVIEW_REQUIRED` | 46.24% | 42.06% | -4.18% | -25.82% | -32.12% | -6.30% | 597 | 388 | 21.47% | 6.12% | 7.70% |

Rules:
- This file is operator review only; it is not a trade instruction.
- `broker_ledger_execution_policy_next_close` is a research challenger metric, not the official production metric.
- Promotion still requires the official broker-ledger path, stress windows, cost sensitivity, and human approval.
