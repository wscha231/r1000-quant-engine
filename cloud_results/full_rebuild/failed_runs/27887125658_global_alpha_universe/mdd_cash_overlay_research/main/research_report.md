# MDD Cash Overlay Research - main

Artifact-only research replay. Daily crisis state is observed at close and applied to the next trading interval.

| Metric | Base broker replay | Cash overlay | Delta |
| --- | ---: | ---: | ---: |
| CAGR | 34.28% | 20.78% | -13.50% |
| MaxDD | -27.18% | -23.97% | 3.21% |
| Sharpe | 1.256 | 0.956 | -0.300 |
| Avg Cash | 26.60% | 42.93% | 16.33% |

## Base MDD Trade Window

- Window: `2020-02-19` to `2020-03-18`
- Raw executions inside window: `17`
- Gross traded: `$51,800`
- Net cash delta from executions: `$39,102`

## Cash Overlay

- Crisis state source: `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/alphaops_vnext/daily_crisis_state.csv`
- Cash actions: `302`
- Estimated cash-action cost: `$14,591`
- Confirm days: `2`
- Release step: `10.00%`

## Variant Sweep

- Best variant: `crisis_only_fast_reentry`
- Best CAGR / MaxDD: `31.50%` / `-26.36%`
- Best target pass: `False`
- Best cash actions: `158`

Research-only. Promotion requires an account-ledger implementation with real orders and next-close fills.
