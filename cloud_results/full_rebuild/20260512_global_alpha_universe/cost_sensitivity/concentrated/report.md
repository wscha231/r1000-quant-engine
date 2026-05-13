# Cost Sensitivity Sidecar — concentrated

- Target book: `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/reports/operating_concentrated_target_book.csv`
- Baseline cost: `25.0 bps`
- Levels run: `25.0, 50.0, 75.0, 100.0 bps`
- Breakeven cost (first level where CAGR < 0): `None`

| Cost bps | CAGR | Sharpe | MaxDD | Trades | Fees USD | dCAGR pp vs base |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 25 | 36.41% | 1.186 | -38.45% | 394 | 73729 | +0.00 |
| 50 | 31.63% | 1.066 | -38.68% | 395 | 125486 | -4.78 |
| 75 | 27.02% | 0.947 | -38.72% | 395 | 160904 | -9.40 |
| 100 | 22.54% | 0.827 | -39.01% | 395 | 184236 | -13.87 |

Research-only sidecar. Higher cost levels stress the CAGR of high-turnover policies; a policy whose CAGR delta worsens by more than the policy's max_cagr_regression_pp at 50 bps should not be promoted.
