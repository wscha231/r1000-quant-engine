# Execution Lag Review

Research-only review of whether account-aware execution replay reduces current/target drift, churn, or drawdown.

- Production activation allowed: `false`
- Official metric required: `broker_ledger_next_close`
- Cash policy flag: `cash_above_target`

| Portfolio | Decision | Base CAGR | Exec CAGR | CAGR Delta | Base MDD | Exec MDD | MDD Improvement | Base Trades | Exec Trades | Preview Turnover | Current Cash | Projected Cash |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| main | `REVIEW_REQUIRED` | 35.21% | 33.45% | -1.77% | -41.43% | -38.99% | 2.43% | 1,749 | 1,054 | 175.48% | 14.39% | 4.33% |
| concentrated | `RESEARCH_CANDIDATE_MDD_IMPROVED` | 25.73% | 27.91% | 2.18% | -62.51% | -56.33% | 6.18% | 593 | 441 | 129.60% | 15.51% | 0.18% |

Rules:
- This file is operator review only; it is not a trade instruction.
- `broker_ledger_execution_policy_next_close` is a research challenger metric, not the official production metric.
- Promotion still requires the official broker-ledger path, stress windows, cost sensitivity, and human approval.
