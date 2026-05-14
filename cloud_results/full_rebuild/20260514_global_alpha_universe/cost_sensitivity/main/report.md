# Cost Sensitivity Sidecar — main

- Target book: `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/reports/operating_main_target_book.csv`
- Baseline cost: `25.0 bps`
- Levels run: `25.0, 50.0, 75.0, 100.0 bps`
- Breakeven cost (first level where CAGR < 0): `None`

| Cost bps | CAGR | Sharpe | MaxDD | Trades | Fees USD | dCAGR pp vs base |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 25 | 23.10% | 1.090 | -29.98% | 2727 | 39076 | +0.00 |
| 50 | 19.65% | 0.957 | -32.55% | 2723 | 69493 | -3.44 |
| 75 | 16.20% | 0.816 | -35.43% | 2712 | 92626 | -6.90 |
| 100 | 12.91% | 0.681 | -38.00% | 2707 | 110236 | -10.19 |

Research-only sidecar. Higher cost levels stress the CAGR of high-turnover policies; a policy whose CAGR delta worsens by more than the policy's max_cagr_regression_pp at 50 bps should not be promoted.
