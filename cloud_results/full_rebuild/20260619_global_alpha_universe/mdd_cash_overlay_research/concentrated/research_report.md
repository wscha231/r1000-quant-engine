# MDD Cash Overlay Research - concentrated

Artifact-only research replay. Daily crisis state is observed at close and applied to the next trading interval.

| Metric | Base broker replay | Cash overlay | Delta |
| --- | ---: | ---: | ---: |
| CAGR | 50.62% | 22.43% | -28.19% |
| MaxDD | -23.83% | -23.87% | -0.04% |
| Sharpe | 1.518 | 1.058 | -0.460 |
| Avg Cash | 42.25% | 66.77% | 24.53% |

## Base MDD Trade Window

- Window: `2021-11-18` to `2023-08-17`
- Raw executions inside window: `142`
- Gross traded: `$1,577,572`
- Net cash delta from executions: `$-8,956`

## Cash Overlay

- Crisis state source: `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/alphaops_vnext/daily_crisis_state.csv`
- Cash actions: `206`
- Estimated cash-action cost: `$10,794`
- Confirm days: `2`
- Release step: `10.00%`

## Variant Sweep

- Best variant: `late_dd_fast_release`
- Best CAGR / MaxDD: `45.96%` / `-24.21%`
- Best target pass: `False`
- Best cash actions: `104`

Research-only. Promotion requires an account-ledger implementation with real orders and next-close fills.
