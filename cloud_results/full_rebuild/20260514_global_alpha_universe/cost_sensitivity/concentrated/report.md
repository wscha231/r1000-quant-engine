# Cost Sensitivity Sidecar — concentrated

- Target book: `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/reports/operating_concentrated_target_book.csv`
- Baseline cost: `25.0 bps`
- Levels run: `25.0, 50.0, 75.0, 100.0 bps`
- Breakeven cost (first level where CAGR < 0): `None`

| Cost bps | CAGR | Sharpe | MaxDD | Trades | Fees USD | dCAGR pp vs base |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 25 | 33.00% | 1.094 | -41.82% | 402 | 69818 | +0.00 |
| 50 | 27.92% | 0.965 | -44.31% | 402 | 117845 | -5.08 |
| 75 | 23.00% | 0.836 | -46.71% | 402 | 149841 | -9.99 |
| 100 | 18.31% | 0.707 | -49.01% | 401 | 170689 | -14.69 |

Research-only sidecar. Higher cost levels stress the CAGR of high-turnover policies; a policy whose CAGR delta worsens by more than the policy's max_cagr_regression_pp at 50 bps should not be promoted.
