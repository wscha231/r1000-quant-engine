# Cost Sensitivity Sidecar — main

- Target book: `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/reports/operating_main_target_book.csv`
- Baseline cost: `25.0 bps`
- Levels run: `25.0, 50.0, 75.0, 100.0 bps`
- Breakeven cost (first level where CAGR < 0): `None`

| Cost bps | CAGR | Sharpe | MaxDD | Trades | Fees USD | dCAGR pp vs base |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 25 | 20.35% | 0.991 | -33.45% | 2737 | 38384 | +0.00 |
| 50 | 16.94% | 0.854 | -35.35% | 2727 | 68128 | -3.41 |
| 75 | 13.65% | 0.718 | -37.22% | 2720 | 91085 | -6.69 |
| 100 | 10.53% | 0.586 | -38.93% | 2716 | 109045 | -9.82 |

Research-only sidecar. Higher cost levels stress the CAGR of high-turnover policies; a policy whose CAGR delta worsens by more than the policy's max_cagr_regression_pp at 50 bps should not be promoted.
