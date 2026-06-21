# AutoLearning Policy Candidate Summary

This candidate is proposal-only. It does not change production defaults.

## Evidence

- Main CAGR: 34.87%
- Main Sharpe: 1.8683127723787383
- Main MaxDD: -14.78%
- Main average stock names: 25.43
- Concentrated CAGR: 54.91%
- Concentrated Sharpe: 1.8118870549611277
- Concentrated MaxDD: -14.70%
- Main trade count: 764
- Concentrated trade count: 206
- Combined trade count: 970
- Combined win rate: 55.15%
- Feature-gate candidates carried forward: 4

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
