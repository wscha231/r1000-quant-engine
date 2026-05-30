# Concentrated Broker Variant Review

Research-only broker-ledger review of concentrated historical grid variants.

- Production activation allowed: `false`
- Baseline variant: `N3_score_power_I1`
- Official concentrated CAGR/MDD: 33.20% / -39.88%
- Official end date: `2026-05-29`

| Variant | Decision | CAGR | MDD | Sharpe | CAGR vs Base | MDD vs Base | Trades | Avg Cash | End | Promotion Valid |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | ---: |
| N10_score_power_I1 | `REJECT_CAGR_DRAG` | 25.14% | -34.83% | 1.038 | -8.05% | 5.05% | 1,337 | 0.09% | 2026-05-29 | true |
| N7_score_power_I2 | `REJECT_MDD` | 24.94% | -35.40% | 1.036 | -8.26% | 4.49% | 712 | 4.78% | 2026-05-29 | true |
| N5_score_power_I1 | `REJECT_MDD` | 27.52% | -36.26% | 1.005 | -5.68% | 3.63% | 670 | 0.06% | 2026-05-29 | true |
| N7_score_power_I1 | `REJECT_MDD` | 25.56% | -36.76% | 1.003 | -7.64% | 3.13% | 930 | 0.06% | 2026-05-29 | true |
| N5_score_power_I2 | `REJECT_MDD` | 26.01% | -37.37% | 1.001 | -7.19% | 2.51% | 518 | 4.39% | 2026-05-29 | true |
| N3_score_power_I1 | `REJECT_MDD` | 33.20% | -39.88% | 1.087 | 0.00% | 0.00% | 403 | 0.05% | 2026-05-29 | true |

Rules:
- This is not a trade instruction.
- Variants that do not reach the official broker end date are extension candidates only.
- Promotion still requires current target-book generation, official broker-ledger replay, cost sensitivity, and human approval.
