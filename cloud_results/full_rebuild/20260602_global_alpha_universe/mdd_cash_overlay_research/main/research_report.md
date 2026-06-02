# MDD Cash Overlay Research - main

Artifact-only research replay. Daily crisis state is observed at close and applied to the next trading interval.

| Metric | Base broker replay | Cash overlay | Delta |
| --- | ---: | ---: | ---: |
| CAGR | 35.21% | 22.03% | -13.18% |
| MaxDD | -41.43% | -27.80% | 13.63% |
| Sharpe | 1.133 | 1.051 | -0.082 |
| Avg Cash | 9.91% | 47.27% | 37.36% |

## Base MDD Trade Window

- Window: `2021-11-19` to `2022-09-26`
- Raw executions inside window: `213`
- Gross traded: `$2,060,843`
- Net cash delta from executions: `$26,536`

## Cash Overlay

- Crisis state source: `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/alphaops_vnext/daily_crisis_state.csv`
- Cash actions: `190`
- Estimated cash-action cost: `$10,888`
- Confirm days: `2`
- Release step: `10.00%`

## Variant Sweep

- Best variant: `crisis_only_fast_reentry`
- Best CAGR / MaxDD: `33.20%` / `-37.18%`
- Best target pass: `False`
- Best cash actions: `112`

Research-only. Promotion requires an account-ledger implementation with real orders and next-close fills.
