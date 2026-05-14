# Cost Sensitivity Sidecar — concentrated

- Target book: `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/reports/operating_concentrated_target_book.csv`
- Baseline cost: `25.0 bps`
- Levels run: `25.0, 50.0, 75.0, 100.0 bps`
- Breakeven cost (first level where CAGR < 0): `None`

| Cost bps | CAGR | Sharpe | MaxDD | Trades | Fees USD | dCAGR pp vs base |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 25 | 29.42% | 1.078 | -32.56% | 280 | 58620 | +0.00 |
| 50 | 24.97% | 0.950 | -34.34% | 281 | 100804 | -4.44 |
| 75 | 20.67% | 0.822 | -36.73% | 280 | 130502 | -8.74 |
| 100 | 16.52% | 0.694 | -39.44% | 279 | 150879 | -12.90 |

Research-only sidecar. Higher cost levels stress the CAGR of high-turnover policies; a policy whose CAGR delta worsens by more than the policy's max_cagr_regression_pp at 50 bps should not be promoted.
