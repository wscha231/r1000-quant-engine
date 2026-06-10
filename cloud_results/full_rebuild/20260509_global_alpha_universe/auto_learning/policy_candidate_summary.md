# AutoLearning Policy Candidate Summary

This candidate is proposal-only. It does not change production defaults.

## Evidence

- Main CAGR: 27.86%
- Main Sharpe: 1.6498608070881968
- Main MaxDD: -16.84%
- Main average stock names: 24.01
- Concentrated CAGR: 45.90%
- Concentrated Sharpe: 1.9039986545320031
- Concentrated MaxDD: -13.46%
- Main trade count: 751
- Concentrated trade count: 244
- Combined trade count: 995
- Combined win rate: 58.29%
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
