# Cost Sensitivity Sidecar — concentrated

- Target book: `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/reports/operating_concentrated_target_book.csv`
- Baseline cost: `25.0 bps`
- Levels run: `25.0, 50.0, 75.0, 100.0 bps`
- Breakeven cost (first level where CAGR < 0): `None`

| Cost bps | CAGR | Sharpe | MaxDD | Trades | Fees USD | dCAGR pp vs base |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 25 | 35.19% | 1.303 | -22.68% | 639 | 65184 | +0.00 |
| 50 | 31.33% | 1.177 | -24.05% | 638 | 114570 | -3.87 |
| 75 | 27.58% | 1.052 | -25.38% | 638 | 151478 | -7.61 |
| 100 | 23.93% | 0.926 | -27.00% | 638 | 178558 | -11.26 |

Research-only sidecar. Higher cost levels stress the CAGR of high-turnover policies; a policy whose CAGR delta worsens by more than the policy's max_cagr_regression_pp at 50 bps should not be promoted.
