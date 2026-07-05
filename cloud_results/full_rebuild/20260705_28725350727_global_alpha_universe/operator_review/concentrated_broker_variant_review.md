# Concentrated Broker Variant Review

Research-only broker-ledger review of concentrated historical grid variants.

- Production activation allowed: `false`
- Baseline variant: `N3_score_power_I1`
- Official concentrated CAGR/MDD: 46.99% / -23.22%
- Official end date: `2026-07-02`

| Variant | Decision | CAGR | MDD | Sharpe | CAGR vs Base | MDD vs Base | Trades | Avg Cash | End | Promotion Valid |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | ---: |
| N10_score_power_I1 | `REJECT_CAGR_DRAG` | 26.70% | -34.28% | 1.089 | -15.44% | 9.53% | 1,348 | 0.09% | 2026-07-02 | true |
| N7_score_power_I1 | `REJECT_MDD` | 29.12% | -37.73% | 1.110 | -13.02% | 6.08% | 943 | 0.04% | 2026-07-02 | true |
| N7_score_power_I2 | `REJECT_MDD` | 23.15% | -37.87% | 0.931 | -19.00% | 5.94% | 715 | 5.02% | 2026-07-02 | true |
| N5_score_power_I1 | `REJECT_MDD` | 33.15% | -42.26% | 1.131 | -9.00% | 1.55% | 673 | 0.04% | 2026-07-02 | true |
| N5_score_power_I2 | `REJECT_MDD` | 25.65% | -42.52% | 0.964 | -16.50% | 1.29% | 523 | 5.72% | 2026-07-02 | true |
| N3_score_power_I1 | `REJECT_MDD` | 42.15% | -43.81% | 1.215 | 0.00% | 0.00% | 419 | 0.04% | 2026-07-02 | true |

Rules:
- This is not a trade instruction.
- Variants that do not reach the official broker end date are extension candidates only.
- Promotion still requires current target-book generation, official broker-ledger replay, cost sensitivity, and human approval.
