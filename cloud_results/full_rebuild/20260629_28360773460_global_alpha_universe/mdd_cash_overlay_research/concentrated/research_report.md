# MDD Cash Overlay Research - concentrated

Artifact-only research replay. Daily crisis state is observed at close and applied to the next trading interval.

| Metric | Base broker replay | Cash overlay | Delta |
| --- | ---: | ---: | ---: |
| CAGR | 46.66% | 17.08% | -29.58% |
| MaxDD | -24.12% | -23.58% | 0.54% |
| Sharpe | 1.401 | 0.843 | -0.557 |
| Avg Cash | 40.48% | 65.04% | 24.55% |

## Base MDD Trade Window

- Window: `2021-11-19` to `2023-03-15`
- Raw executions inside window: `112`
- Gross traded: `$1,296,021`
- Net cash delta from executions: `$706`

## Cash Overlay

- Crisis state source: `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/alphaops_vnext/daily_crisis_state.csv`
- Cash actions: `263`
- Estimated cash-action cost: `$15,108`
- Confirm days: `2`
- Release step: `10.00%`

## Variant Sweep

- Best variant: `crisis_only_confirm2`
- Best CAGR / MaxDD: `40.91%` / `-24.18%`
- Best target pass: `False`
- Best cash actions: `204`

Research-only. Promotion requires an account-ledger implementation with real orders and next-close fills.
