# Concentrated Broker Variant Review

Research-only broker-ledger review of concentrated historical grid variants.

- Production activation allowed: `false`
- Baseline variant: `N3_score_power_I1`
- Official concentrated CAGR/MDD: 46.24% / -25.82%
- Official end date: `2026-06-23`

| Variant | Decision | CAGR | MDD | Sharpe | CAGR vs Base | MDD vs Base | Trades | Avg Cash | End | Promotion Valid |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | ---: |
| N7_score_power_I2 | `REJECT_MDD` | 23.33% | -37.03% | 0.933 | -11.71% | 7.87% | 708 | 5.09% | 2026-06-23 | true |
| N10_score_power_I1 | `REJECT_MDD` | 24.29% | -37.17% | 1.017 | -10.75% | 7.73% | 1,322 | 0.07% | 2026-06-23 | true |
| N7_score_power_I1 | `REJECT_MDD` | 27.42% | -38.91% | 1.065 | -7.61% | 6.00% | 929 | 0.05% | 2026-06-23 | true |
| N5_score_power_I1 | `REJECT_MDD` | 32.27% | -40.16% | 1.125 | -2.76% | 4.75% | 664 | 0.05% | 2026-06-23 | true |
| N5_score_power_I2 | `REJECT_MDD` | 26.58% | -41.10% | 0.983 | -8.46% | 3.81% | 517 | 5.16% | 2026-06-23 | true |
| N3_score_power_I1 | `REJECT_MDD` | 35.03% | -44.90% | 1.128 | 0.00% | 0.00% | 405 | 0.03% | 2026-06-23 | true |

Rules:
- This is not a trade instruction.
- Variants that do not reach the official broker end date are extension candidates only.
- Promotion still requires current target-book generation, official broker-ledger replay, cost sensitivity, and human approval.
