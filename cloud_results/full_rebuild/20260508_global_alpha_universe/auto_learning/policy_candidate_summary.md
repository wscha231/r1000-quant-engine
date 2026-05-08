# AutoLearning Policy Candidate Summary

This candidate is proposal-only. It does not change production defaults.

## Evidence

- Main CAGR: 0.00%
- Main Sharpe: 0.0
- Main MaxDD: 0.00%
- Main average stock names: 0.00
- Concentrated CAGR: 0.00%
- Concentrated Sharpe: 0.0
- Concentrated MaxDD: 0.00%
- Main trade count: 0
- Concentrated trade count: 0
- Combined trade count: 0
- Combined win rate: 0.00%
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
