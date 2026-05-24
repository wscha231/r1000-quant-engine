# Cost Sensitivity Sidecar — main

- Target book: `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/reports/operating_main_target_book.csv`
- Baseline cost: `25.0 bps`
- Levels run: `25.0, 50.0, 75.0, 100.0 bps`
- Breakeven cost (first level where CAGR < 0): `None`

| Cost bps | CAGR | Sharpe | MaxDD | Trades | Fees USD | dCAGR pp vs base |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 25 | 21.45% | 1.044 | -32.45% | 2127 | 38329 | +0.00 |
| 50 | 17.97% | 0.903 | -34.90% | 2123 | 68147 | -3.48 |
| 75 | 14.66% | 0.765 | -37.43% | 2119 | 91512 | -6.79 |
| 100 | 11.31% | 0.622 | -39.77% | 2110 | 109264 | -10.15 |

Research-only sidecar. Higher cost levels stress the CAGR of high-turnover policies; a policy whose CAGR delta worsens by more than the policy's max_cagr_regression_pp at 50 bps should not be promoted.
