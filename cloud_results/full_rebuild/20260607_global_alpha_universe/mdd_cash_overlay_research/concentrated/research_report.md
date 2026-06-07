# MDD Cash Overlay Research - concentrated

Artifact-only research replay. Daily crisis state is observed at close and applied to the next trading interval.

| Metric | Base broker replay | Cash overlay | Delta |
| --- | ---: | ---: | ---: |
| CAGR | 37.34% | 14.85% | -22.48% |
| MaxDD | -31.72% | -25.67% | 6.05% |
| Sharpe | 1.271 | 0.799 | -0.473 |
| Avg Cash | 44.25% | 67.23% | 22.98% |

## Base MDD Trade Window

- Window: `2021-09-03` to `2023-03-15`
- Raw executions inside window: `127`
- Gross traded: `$1,381,215`
- Net cash delta from executions: `$11,557`

## Cash Overlay

- Crisis state source: `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/alphaops_vnext/daily_crisis_state.csv`
- Cash actions: `221`
- Estimated cash-action cost: `$10,139`
- Confirm days: `2`
- Release step: `10.00%`

## Variant Sweep

- Best variant: `crisis_only_confirm2`
- Best CAGR / MaxDD: `32.78%` / `-31.06%`
- Best target pass: `False`
- Best cash actions: `196`

Research-only. Promotion requires an account-ledger implementation with real orders and next-close fills.
