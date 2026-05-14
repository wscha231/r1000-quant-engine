# Cost Sensitivity Sidecar — main

- Target book: `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/reports/operating_main_target_book.csv`
- Baseline cost: `25.0 bps`
- Levels run: `25.0, 50.0, 75.0, 100.0 bps`
- Breakeven cost (first level where CAGR < 0): `None`

| Cost bps | CAGR | Sharpe | MaxDD | Trades | Fees USD | dCAGR pp vs base |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 25 | 20.20% | 1.057 | -32.02% | 2791 | 34259 | +0.00 |
| 50 | 16.95% | 0.914 | -34.28% | 2784 | 61137 | -3.26 |
| 75 | 13.87% | 0.775 | -36.29% | 2776 | 82394 | -6.34 |
| 100 | 10.76% | 0.631 | -38.31% | 2769 | 98759 | -9.44 |

Research-only sidecar. Higher cost levels stress the CAGR of high-turnover policies; a policy whose CAGR delta worsens by more than the policy's max_cagr_regression_pp at 50 bps should not be promoted.
