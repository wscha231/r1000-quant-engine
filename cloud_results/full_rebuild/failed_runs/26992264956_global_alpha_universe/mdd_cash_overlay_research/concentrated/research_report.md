# MDD Cash Overlay Research - concentrated

Artifact-only research replay. Daily crisis state is observed at close and applied to the next trading interval.

| Metric | Base broker replay | Cash overlay | Delta |
| --- | ---: | ---: | ---: |
| CAGR | 39.79% | 12.45% | -27.34% |
| MaxDD | -35.20% | -25.38% | 9.83% |
| Sharpe | 1.185 | 0.678 | -0.507 |
| Avg Cash | 31.97% | 67.82% | 35.85% |

## Base MDD Trade Window

- Window: `2021-02-12` to `2023-09-26`
- Raw executions inside window: `228`
- Gross traded: `$4,236,645`
- Net cash delta from executions: `$-59,670`

## Cash Overlay

- Crisis state source: `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/alphaops_vnext/daily_crisis_state.csv`
- Cash actions: `203`
- Estimated cash-action cost: `$8,901`
- Confirm days: `2`
- Release step: `10.00%`

## Variant Sweep

- Best variant: `crisis_only_confirm2`
- Best CAGR / MaxDD: `33.84%` / `-31.98%`
- Best target pass: `False`
- Best cash actions: `190`

Research-only. Promotion requires an account-ledger implementation with real orders and next-close fills.
