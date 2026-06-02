# Concentrated Broker Variant Review

Research-only broker-ledger review of concentrated historical grid variants.

- Production activation allowed: `false`
- Baseline variant: `N3_score_power_I1`
- Official concentrated CAGR/MDD: 25.73% / -62.51%
- Official end date: `2026-06-01`

| Variant | Decision | CAGR | MDD | Sharpe | CAGR vs Base | MDD vs Base | Trades | Avg Cash | End | Promotion Valid |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | ---: |
| N5_score_power_I2 | `REJECT_MDD` | 28.90% | -38.01% | 1.056 | -5.63% | 2.22% | 512 | 4.63% | 2026-06-01 | true |
| N7_score_power_I2 | `REJECT_MDD` | 28.71% | -38.45% | 1.104 | -5.83% | 1.78% | 694 | 4.91% | 2026-06-01 | true |
| N10_score_power_I1 | `REJECT_MDD` | 23.23% | -39.70% | 0.973 | -11.30% | 0.54% | 1,314 | 0.10% | 2026-06-01 | true |
| N5_score_power_I1 | `REJECT_MDD` | 28.27% | -40.20% | 1.025 | -6.26% | 0.03% | 663 | 0.05% | 2026-06-01 | true |
| N3_score_power_I1 | `REJECT_MDD` | 34.53% | -40.23% | 1.110 | 0.00% | 0.00% | 404 | 0.03% | 2026-06-01 | true |
| N7_score_power_I1 | `REJECT_MDD` | 24.83% | -42.57% | 0.977 | -9.70% | -2.34% | 922 | 0.06% | 2026-06-01 | true |

Rules:
- This is not a trade instruction.
- Variants that do not reach the official broker end date are extension candidates only.
- Promotion still requires current target-book generation, official broker-ledger replay, cost sensitivity, and human approval.
