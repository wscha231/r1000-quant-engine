# Cost Sensitivity Sidecar — main

- Target book: `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/reports/operating_main_target_book.csv`
- Baseline cost: `25.0 bps`
- Levels run: `25.0, 50.0, 75.0, 100.0 bps`
- Breakeven cost (first level where CAGR < 0): `None`

| Cost bps | CAGR | Sharpe | MaxDD | Trades | Fees USD | dCAGR pp vs base |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 25 | 19.92% | 0.918 | -32.13% | 2796 | 32627 | +0.00 |
| 50 | 16.79% | 0.780 | -34.37% | 2787 | 58466 | -3.13 |
| 75 | 13.68% | 0.639 | -36.37% | 2781 | 78741 | -6.23 |
| 100 | 10.69% | 0.501 | -38.49% | 2774 | 94627 | -9.23 |

Research-only sidecar. Higher cost levels stress the CAGR of high-turnover policies; a policy whose CAGR delta worsens by more than the policy's max_cagr_regression_pp at 50 bps should not be promoted.
