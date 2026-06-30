# Concentrated Broker Variant Review

Research-only broker-ledger review of concentrated historical grid variants.

- Production activation allowed: `false`
- Baseline variant: `N3_score_power_I1`
- Official concentrated CAGR/MDD: 46.66% / -24.12%
- Official end date: `2026-06-26`

| Variant | Decision | CAGR | MDD | Sharpe | CAGR vs Base | MDD vs Base | Trades | Avg Cash | End | Promotion Valid |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | ---: |
| N10_score_power_I1 | `REJECT_CAGR_DRAG` | 25.70% | -33.66% | 1.066 | -11.31% | 8.08% | 1,324 | 0.07% | 2026-06-26 | true |
| N7_score_power_I2 | `REJECT_MDD` | 23.27% | -38.45% | 0.934 | -13.74% | 3.30% | 713 | 5.13% | 2026-06-26 | true |
| N7_score_power_I1 | `REJECT_MDD` | 28.13% | -39.25% | 1.089 | -8.88% | 2.49% | 933 | 0.05% | 2026-06-26 | true |
| N5_score_power_I2 | `REJECT_MDD` | 26.28% | -40.33% | 0.975 | -10.73% | 1.41% | 527 | 5.03% | 2026-06-26 | true |
| N5_score_power_I1 | `REJECT_MDD` | 32.40% | -40.41% | 1.132 | -4.61% | 1.33% | 666 | 0.04% | 2026-06-26 | true |
| N3_score_power_I1 | `REJECT_MDD` | 37.01% | -41.75% | 1.160 | 0.00% | 0.00% | 411 | 0.04% | 2026-06-26 | true |

Rules:
- This is not a trade instruction.
- Variants that do not reach the official broker end date are extension candidates only.
- Promotion still requires current target-book generation, official broker-ledger replay, cost sensitivity, and human approval.
