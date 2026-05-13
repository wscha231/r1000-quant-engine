# Cost Sensitivity Sidecar — main

- Target book: `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/reports/operating_main_target_book.csv`
- Baseline cost: `25.0 bps`
- Levels run: `25.0, 50.0, 75.0, 100.0 bps`
- Breakeven cost (first level where CAGR < 0): `None`

| Cost bps | CAGR | Sharpe | MaxDD | Trades | Fees USD | dCAGR pp vs base |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 25 | 21.38% | 1.026 | -33.19% | 2091 | 37667 | +0.00 |
| 50 | 17.95% | 0.890 | -35.23% | 2083 | 66884 | -3.43 |
| 75 | 14.62% | 0.753 | -37.21% | 2075 | 89577 | -6.77 |
| 100 | 11.45% | 0.621 | -39.37% | 2073 | 107240 | -9.93 |

Research-only sidecar. Higher cost levels stress the CAGR of high-turnover policies; a policy whose CAGR delta worsens by more than the policy's max_cagr_regression_pp at 50 bps should not be promoted.
