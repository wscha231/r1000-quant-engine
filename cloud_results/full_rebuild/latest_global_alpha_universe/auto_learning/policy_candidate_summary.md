# AutoLearning Policy Candidate Summary

This candidate is proposal-only. It does not change production defaults.

## Evidence

- Main CAGR: 29.42%
- Main Sharpe: 1.7135178432451776
- Main MaxDD: -16.25%
- Main average stock names: 25.72
- Concentrated CAGR: 47.20%
- Concentrated Sharpe: 1.6761379600533215
- Concentrated MaxDD: -20.10%
- Main trade count: 772
- Concentrated trade count: 154
- Combined trade count: 926
- Combined win rate: 57.02%
- Feature-gate candidates carried forward: 1

## Candidate Scope

- Feature gates: carry forward existing bear regime proposals.
- Main v2: propose sleeve allocation and target-N policies.
- Concentrated: propose capacity, cap, entry, and exit policy candidates.
- Alpha Sprint: propose bull-only activation and risk rules.
- Orchestrator: propose regime capital maps for challenger backtest only.

## Validation

- Schema valid: True
- Issues: none

## Next Required Step

Build `tools/auto_policy_challenger.py` to run this policy as a challenger against legacy champion metrics.
