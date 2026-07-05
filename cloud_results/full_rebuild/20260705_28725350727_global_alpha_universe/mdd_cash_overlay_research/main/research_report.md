# MDD Cash Overlay Research - main

Artifact-only research replay. Daily crisis state is observed at close and applied to the next trading interval.

| Metric | Base broker replay | Cash overlay | Delta |
| --- | ---: | ---: | ---: |
| CAGR | 32.94% | 21.96% | -10.98% |
| MaxDD | -25.65% | -24.25% | 1.41% |
| Sharpe | 1.237 | 0.982 | -0.255 |
| Avg Cash | 29.34% | 42.46% | 13.12% |

## Base MDD Trade Window

- Window: `2021-11-19` to `2022-09-26`
- Raw executions inside window: `203`
- Gross traded: `$1,100,352`
- Net cash delta from executions: `$110,011`

## Cash Overlay

- Crisis state source: `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/alphaops_vnext/daily_crisis_state.csv`
- Cash actions: `234`
- Estimated cash-action cost: `$12,733`
- Confirm days: `2`
- Release step: `10.00%`

## Variant Sweep

- Best variant: `crisis_only_fast_reentry`
- Best CAGR / MaxDD: `30.39%` / `-25.23%`
- Best target pass: `False`
- Best cash actions: `149`

Research-only. Promotion requires an account-ledger implementation with real orders and next-close fills.
