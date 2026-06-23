# Concentrated Broker Variant Review

Research-only broker-ledger review of concentrated historical grid variants.

- Production activation allowed: `false`
- Baseline variant: `N3_score_power_I1`
- Official concentrated CAGR/MDD: 45.96% / -24.60%
- Official end date: `2026-06-22`

| Variant | Decision | CAGR | MDD | Sharpe | CAGR vs Base | MDD vs Base | Trades | Avg Cash | End | Promotion Valid |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | ---: |
| N7_score_power_I2 | `REJECT_CAGR_DRAG` | 26.57% | -34.90% | 1.079 | -8.46% | 4.65% | 709 | 5.80% | 2026-06-22 | true |
| N5_score_power_I1 | `REJECT_MDD` | 30.67% | -35.72% | 1.091 | -4.36% | 3.83% | 667 | 0.05% | 2026-06-22 | true |
| N7_score_power_I1 | `REJECT_MDD` | 27.67% | -36.58% | 1.058 | -7.36% | 2.97% | 925 | 0.06% | 2026-06-22 | true |
| N5_score_power_I2 | `REJECT_MDD` | 25.36% | -37.29% | 0.985 | -9.68% | 2.26% | 500 | 5.83% | 2026-06-22 | true |
| N10_score_power_I1 | `REJECT_MDD` | 21.71% | -37.33% | 0.928 | -13.33% | 2.22% | 1,322 | 0.10% | 2026-06-22 | true |
| N3_score_power_I1 | `REJECT_MDD` | 35.04% | -39.55% | 1.112 | 0.00% | 0.00% | 403 | 0.04% | 2026-06-22 | true |

Rules:
- This is not a trade instruction.
- Variants that do not reach the official broker end date are extension candidates only.
- Promotion still requires current target-book generation, official broker-ledger replay, cost sensitivity, and human approval.
