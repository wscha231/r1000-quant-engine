# Cost Sensitivity Sidecar — concentrated

- Target book: `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/reports/operating_concentrated_target_book.csv`
- Baseline cost: `25.0 bps`
- Levels run: `25.0, 50.0, 75.0, 100.0 bps`
- Breakeven cost (first level where CAGR < 0): `None`

| Cost bps | CAGR | Sharpe | MaxDD | Trades | Fees USD | dCAGR pp vs base |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 25 | 16.97% | 0.725 | -33.80% | 922 | 47673 | +0.00 |
| 50 | 12.90% | 0.560 | -34.12% | 921 | 82661 | -4.08 |
| 75 | 8.89% | 0.392 | -34.41% | 920 | 107696 | -8.09 |
| 100 | 5.03% | 0.227 | -34.70% | 919 | 125464 | -11.94 |

Research-only sidecar. Higher cost levels stress the CAGR of high-turnover policies; a policy whose CAGR delta worsens by more than the policy's max_cagr_regression_pp at 50 bps should not be promoted.
