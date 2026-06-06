# MDD Cash Overlay Research - concentrated

Artifact-only research replay. Daily crisis state is observed at close and applied to the next trading interval.

| Metric | Base broker replay | Cash overlay | Delta |
| --- | ---: | ---: | ---: |
| CAGR | 38.66% | 14.87% | -23.79% |
| MaxDD | -27.26% | -25.48% | 1.78% |
| Sharpe | 1.305 | 0.796 | -0.509 |
| Avg Cash | 44.36% | 67.00% | 22.64% |

## Base MDD Trade Window

- Window: `2021-09-03` to `2023-03-15`
- Raw executions inside window: `126`
- Gross traded: `$1,333,440`
- Net cash delta from executions: `$14,551`

## Cash Overlay

- Crisis state source: `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/alphaops_vnext/daily_crisis_state.csv`
- Cash actions: `230`
- Estimated cash-action cost: `$10,609`
- Confirm days: `2`
- Release step: `10.00%`

## Variant Sweep

- Best variant: `crisis_only_confirm2`
- Best CAGR / MaxDD: `34.04%` / `-26.54%`
- Best target pass: `False`
- Best cash actions: `197`

Research-only. Promotion requires an account-ledger implementation with real orders and next-close fills.
