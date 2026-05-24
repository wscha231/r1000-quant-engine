# Cost Sensitivity Sidecar — concentrated

- Target book: `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/reports/operating_concentrated_target_book.csv`
- Baseline cost: `25.0 bps`
- Levels run: `25.0, 50.0, 75.0, 100.0 bps`
- Breakeven cost (first level where CAGR < 0): `None`

| Cost bps | CAGR | Sharpe | MaxDD | Trades | Fees USD | dCAGR pp vs base |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 25 | 36.61% | 1.100 | -42.58% | 276 | 66691 | +0.00 |
| 50 | 31.15% | 0.978 | -45.00% | 276 | 111843 | -5.46 |
| 75 | 25.92% | 0.856 | -47.93% | 274 | 141613 | -10.70 |
| 100 | 20.89% | 0.734 | -50.68% | 276 | 160406 | -15.72 |

Research-only sidecar. Higher cost levels stress the CAGR of high-turnover policies; a policy whose CAGR delta worsens by more than the policy's max_cagr_regression_pp at 50 bps should not be promoted.
