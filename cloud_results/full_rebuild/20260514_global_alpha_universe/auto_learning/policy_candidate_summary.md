# AutoLearning Policy Candidate Summary

This candidate is proposal-only. It does not change production defaults.

## Evidence

- Main CAGR: 30.99%
- Main Sharpe: 1.7070972870997103
- Main MaxDD: -17.41%
- Main average stock names: 26.08
- Concentrated CAGR: 55.12%
- Concentrated Sharpe: 1.7167511376775713
- Concentrated MaxDD: -14.00%
- Main trade count: 782
- Concentrated trade count: 155
- Combined trade count: 937
- Combined win rate: 56.03%
- Feature-gate candidates carried forward: 0

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
