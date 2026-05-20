# AutoLearning Policy Candidate Summary

This candidate is proposal-only. It does not change production defaults.

## Evidence

- Main CAGR: 29.19%
- Main Sharpe: 1.7248976396719429
- Main MaxDD: -17.46%
- Main average stock names: 26.22
- Concentrated CAGR: 48.94%
- Concentrated Sharpe: 1.7406704160388327
- Concentrated MaxDD: -16.67%
- Main trade count: 737
- Concentrated trade count: 150
- Combined trade count: 887
- Combined win rate: 57.27%
- Feature-gate candidates carried forward: 3

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
