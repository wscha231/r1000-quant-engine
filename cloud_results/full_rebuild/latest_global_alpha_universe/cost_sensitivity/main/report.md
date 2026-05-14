# Cost Sensitivity Sidecar — main

- Target book: `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/reports/operating_main_target_book.csv`
- Baseline cost: `25.0 bps`
- Levels run: `25.0, 50.0, 75.0, 100.0 bps`
- Breakeven cost (first level where CAGR < 0): `None`

| Cost bps | CAGR | Sharpe | MaxDD | Trades | Fees USD | dCAGR pp vs base |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 25 | 18.50% | 0.851 | -31.93% | 2842 | 33413 | +0.00 |
| 50 | 15.21% | 0.705 | -34.02% | 2838 | 59611 | -3.29 |
| 75 | 12.25% | 0.571 | -36.02% | 2830 | 80456 | -6.25 |
| 100 | 9.21% | 0.430 | -38.11% | 2817 | 96472 | -9.29 |

Research-only sidecar. Higher cost levels stress the CAGR of high-turnover policies; a policy whose CAGR delta worsens by more than the policy's max_cagr_regression_pp at 50 bps should not be promoted.
