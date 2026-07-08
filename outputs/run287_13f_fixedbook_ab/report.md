# Run287 13F Fixed-Book Broker A/B

- status: `completed`
- decision_label: `reject_oos2_worse`
- pit_gate_status: `clean`
- confirmed swaps: `36`
- unconfirmed reverts: `15`
- broad/miss-set sign agreement: `True`
- No fullrun, hook promotion, threshold grid, production promotion, or live trading.

## Broker Metrics

| Accounting | Arm | CAGR | MaxDD | dCAGR vs official pp | OOS dCAGR pp | OOS2 dCAGR pp | Mission pass | Excess CAGR vs SPY | Down capture | Beta-adj alpha |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- | ---: | ---: | ---: |
| zero_yield | official_baseline | 47.00% | -23.22% | +0.00 | +0.00 | +0.00 | False | +30.11% | 0.994 | 33.72% |
| zero_yield | rq_hook_off_reconstructed | 44.23% | -24.11% | -2.77 | -5.94 | -2.92 | False | +27.34% | 0.995 | 31.87% |
| zero_yield | 13f_confirmed_candidate | 46.83% | -23.21% | -0.17 | +0.68 | -0.04 | False | +29.94% | 0.994 | 33.61% |
| cash_carry | official_baseline | 48.41% | -22.96% | +0.00 | +0.00 | +0.00 | False | +31.52% | 0.994 | 34.67% |
| cash_carry | rq_hook_off_reconstructed | 45.59% | -23.86% | -2.82 | -6.03 | -2.97 | False | +28.70% | 0.995 | 32.81% |
| cash_carry | 13f_confirmed_candidate | 48.21% | -22.96% | -0.20 | +0.65 | -0.06 | False | +31.32% | 0.994 | 34.54% |

## Interpretation

- `official_baseline` is the run287 fixed official book.
- `rq_hook_off_reconstructed` reverts all replacement-quality policy-month replacements to their recorded donor tickers.
- `13f_confirmed_candidate` keeps only replacements whose added ticker has ex-ante pure `w4_13f_score > 0`; unconfirmed replacements are reverted.
- Forward returns appear only in `swaps.csv` as audit labels and are not used for ranking or threshold tuning.
