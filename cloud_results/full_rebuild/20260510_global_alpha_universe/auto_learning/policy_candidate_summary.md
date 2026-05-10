# AutoLearning Policy Candidate Summary

This candidate is proposal-only. It does not change production defaults.

## Evidence

- Main CAGR: 28.47%
- Main Sharpe: 1.6505880825201922
- Main MaxDD: -15.42%
- Main average stock names: 24.72
- Concentrated CAGR: 43.24%
- Concentrated Sharpe: 1.7696899020615104
- Concentrated MaxDD: -12.59%
- Main trade count: 728
- Concentrated trade count: 207
- Combined trade count: 935
- Combined win rate: 57.65%
- Feature-gate candidates carried forward: 2

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
