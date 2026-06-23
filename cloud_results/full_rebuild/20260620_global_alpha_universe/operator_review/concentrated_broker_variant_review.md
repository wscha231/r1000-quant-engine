# Concentrated Broker Variant Review

Research-only broker-ledger review of concentrated historical grid variants.

- Production activation allowed: `false`
- Baseline variant: `N3_score_power_I1`
- Official concentrated CAGR/MDD: 45.47% / -24.59%
- Official end date: `2026-06-18`

| Variant | Decision | CAGR | MDD | Sharpe | CAGR vs Base | MDD vs Base | Trades | Avg Cash | End | Promotion Valid |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | ---: |
| N10_score_power_I1 | `REJECT_CAGR_DRAG` | 24.83% | -33.36% | 1.038 | -14.56% | 6.29% | 1,315 | 0.08% | 2026-06-18 | true |
| N7_score_power_I2 | `REJECT_CAGR_DRAG` | 27.36% | -34.62% | 1.100 | -12.03% | 5.03% | 699 | 5.48% | 2026-06-18 | true |
| N7_score_power_I1 | `REJECT_MDD` | 31.16% | -35.11% | 1.162 | -8.23% | 4.54% | 917 | 0.07% | 2026-06-18 | true |
| N5_score_power_I1 | `REJECT_MDD` | 33.32% | -35.69% | 1.159 | -6.07% | 3.96% | 671 | 0.05% | 2026-06-18 | true |
| N5_score_power_I2 | `REJECT_MDD` | 26.13% | -37.20% | 1.000 | -13.26% | 2.45% | 500 | 5.65% | 2026-06-18 | true |
| N3_score_power_I1 | `REJECT_MDD` | 39.39% | -39.65% | 1.214 | 0.00% | 0.00% | 405 | 0.03% | 2026-06-18 | true |

Rules:
- This is not a trade instruction.
- Variants that do not reach the official broker end date are extension candidates only.
- Promotion still requires current target-book generation, official broker-ledger replay, cost sensitivity, and human approval.
