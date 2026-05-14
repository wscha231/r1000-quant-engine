# Cost Sensitivity Sidecar — concentrated

- Target book: `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/reports/operating_concentrated_target_book.csv`
- Baseline cost: `25.0 bps`
- Levels run: `25.0, 50.0, 75.0, 100.0 bps`
- Breakeven cost (first level where CAGR < 0): `None`

| Cost bps | CAGR | Sharpe | MaxDD | Trades | Fees USD | dCAGR pp vs base |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 25 | 32.65% | 1.071 | -28.85% | 280 | 64915 | +0.00 |
| 50 | 28.16% | 0.946 | -31.46% | 280 | 111712 | -4.49 |
| 75 | 23.85% | 0.822 | -33.97% | 279 | 144996 | -8.80 |
| 100 | 19.68% | 0.698 | -36.38% | 277 | 168057 | -12.97 |

Research-only sidecar. Higher cost levels stress the CAGR of high-turnover policies; a policy whose CAGR delta worsens by more than the policy's max_cagr_regression_pp at 50 bps should not be promoted.
