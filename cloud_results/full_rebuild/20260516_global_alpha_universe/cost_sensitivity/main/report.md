# Cost Sensitivity Sidecar — main

- Target book: `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/reports/operating_main_target_book.csv`
- Baseline cost: `25.0 bps`
- Levels run: `25.0, 50.0, 75.0, 100.0 bps`
- Breakeven cost (first level where CAGR < 0): `None`

| Cost bps | CAGR | Sharpe | MaxDD | Trades | Fees USD | dCAGR pp vs base |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 25 | 12.92% | 0.638 | -27.07% | 2574 | 31356 | +0.00 |
| 50 | 9.75% | 0.477 | -29.02% | 2571 | 56229 | -3.17 |
| 75 | 6.75% | 0.321 | -30.77% | 2569 | 76066 | -6.17 |
| 100 | 3.97% | 0.174 | -32.75% | 2557 | 91535 | -8.95 |

Research-only sidecar. Higher cost levels stress the CAGR of high-turnover policies; a policy whose CAGR delta worsens by more than the policy's max_cagr_regression_pp at 50 bps should not be promoted.
