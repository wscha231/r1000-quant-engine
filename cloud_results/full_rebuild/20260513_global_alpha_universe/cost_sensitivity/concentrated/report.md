# Cost Sensitivity Sidecar — concentrated

- Target book: `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/reports/operating_concentrated_target_book.csv`
- Baseline cost: `25.0 bps`
- Levels run: `25.0, 50.0, 75.0, 100.0 bps`
- Breakeven cost (first level where CAGR < 0): `None`

| Cost bps | CAGR | Sharpe | MaxDD | Trades | Fees USD | dCAGR pp vs base |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 25 | 37.35% | 1.278 | -37.89% | 525 | 81872 | +0.00 |
| 50 | 32.65% | 1.153 | -38.02% | 525 | 139745 | -4.70 |
| 75 | 28.08% | 1.026 | -38.15% | 526 | 179363 | -9.27 |
| 100 | 23.68% | 0.900 | -38.31% | 524 | 205835 | -13.67 |

Research-only sidecar. Higher cost levels stress the CAGR of high-turnover policies; a policy whose CAGR delta worsens by more than the policy's max_cagr_regression_pp at 50 bps should not be promoted.
